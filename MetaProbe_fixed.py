import os
import sys
import re
import json
import struct
import threading
from datetime import datetime
from io import BytesIO

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.uix.textinput import TextInput
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.popup import Popup
from kivy.uix.progressbar import ProgressBar
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.treeview import TreeView, TreeViewNode, TreeViewLabel
from kivy.graphics import Color, Rectangle
from kivy.properties import StringProperty, ObjectProperty, BooleanProperty
from kivy.metrics import dp, sp
from kivy.factory import Factory
from kivy.lang import Builder
from kivy.core.clipboard import Clipboard

# Try to import PIL for image processing
try:
    from PIL import Image as PILImage
    from PIL import ExifTags, ImageDraw
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("Warning: PIL/Pillow is not installed. Image metadata will be limited.")
    print("Install with: pip install pillow")

# Try to import pymediainfo for media file analysis
try:
    import pymediainfo
    HAS_MEDIAINFO = True
except ImportError:
    HAS_MEDIAINFO = False
    print("Warning: pymediainfo is not installed. Video metadata will be limited.")
    print("Install with: pip install pymediainfo")

class MetadataDisplay(BoxLayout):
    def __init__(self, **kwargs):
        super(MetadataDisplay, self).__init__(**kwargs)
        self.current_file = None
        self.current_metadata = {}
        self.detected_ai_prompt = None
        self.row_count = 0  # For alternating row colors
        self.tree_search_results = []
        self.tree_search_index = -1
        self.text_search_positions = {}  # Store search positions for each text widget
        Window.bind(on_drop_file=self._on_drop_file)
        
        # Bind keyboard for search shortcuts
        self._keyboard = Window.request_keyboard(self._keyboard_closed, self)
        self._keyboard.bind(on_key_down=self._on_key_down)

    def extract_ai_metadata_from_image(self, img, file_path):
        """Extract AI metadata from image file"""
        metadata = {}
        prompt = None
        
        # Read the file in binary mode
        with open(file_path, 'rb') as f:
            file_data = f.read()
        
        # 0. Check for direct metadata in image info - highest priority
        if hasattr(img, 'info'):
            # Check Description field - Midjourney often puts prompts here
            if 'Description' in img.info:
                desc_text = str(img.info['Description'])
                if any(marker in desc_text for marker in ['--ar', '--v', '--style', 'Job ID:', '/imagine']):
                    metadata["Generator"] = "Midjourney"
                    metadata["prompt"] = desc_text
                    prompt = desc_text
                    return metadata, prompt
            
            # Check Author field - Often indicates AI generator
            if 'Author' in img.info and img.info['Author']:
                metadata["Author"] = img.info['Author']
        
        # 1. Check for Stable Diffusion metadata
        sd_pattern = re.compile(rb'parameters\s*:\s*(.*?)(?:\n\n|\Z)', re.DOTALL)
        matches = sd_pattern.findall(file_data)
        
        if matches:
            prompt_text = matches[0].decode('utf-8', errors='ignore').strip()
            metadata["Generator"] = "Stable Diffusion"
            metadata["prompt"] = prompt_text
            prompt = prompt_text
            
            # Try to extract additional parameters
            if "Negative prompt:" in prompt_text:
                parts = prompt_text.split("Negative prompt:")
                metadata["positive_prompt"] = parts[0].strip()
                
                neg_and_params = parts[1].strip()
                param_start = neg_and_params.find("Steps: ")
                
                if param_start != -1:
                    metadata["negative_prompt"] = neg_and_params[:param_start].strip()
                    metadata["parameters"] = neg_and_params[param_start:].strip()
                else:
                    metadata["negative_prompt"] = neg_and_params
            
            return metadata, prompt
        
        # 2. Check for Midjourney metadata in EXIF
        if hasattr(img, '_getexif') and img._getexif():
            exif = img._getexif()
            
            # Midjourney often stores in ImageDescription or UserComment
            description_tags = [270, 0x9286, 0x010e]
            for tag in description_tags:
                if tag in exif and exif[tag]:
                    desc_text = exif[tag]
                    if isinstance(desc_text, bytes):
                        try:
                            desc_text = desc_text.decode('utf-8')
                        except UnicodeDecodeError:
                            continue
                    
                    # Look for Midjourney patterns
                    if desc_text and ("--ar" in desc_text or "--v" in desc_text or "/imagine" in desc_text):
                        metadata["Generator"] = "Midjourney"
                        metadata["prompt"] = desc_text
                        prompt = desc_text
                        return metadata, prompt
        
        # 3. Check for DALL-E metadata
        if hasattr(img, '_getexif') and img._getexif():
            exif = img._getexif()
            
            # Check Software field - DALL-E often identifies itself there
            if 305 in exif and exif[305] and "DALL-E" in str(exif[305]):
                metadata["Generator"] = "DALL-E"
                
                # Check for prompt in UserComment or ImageDescription
                for tag in [270, 0x9286, 0x010e]:
                    if tag in exif and exif[tag]:
                        desc = exif[tag]
                        if isinstance(desc, bytes):
                            try:
                                desc = desc.decode('utf-8')
                            except UnicodeDecodeError:
                                continue
                                
                        if desc and len(desc) > 10:
                            metadata["prompt"] = desc
                            prompt = desc
                            return metadata, prompt
        
        # 4. Look for generic metadata in PNG text chunks
        if hasattr(img, 'info'):
            for key in ['parameters', 'prompt', 'sd-metadata', 'ai_metadata']:
                if key in img.info:
                    prompt_text = str(img.info[key])
                    metadata["Generator"] = "AI Image Generator"
                    metadata["prompt"] = prompt_text
                    prompt = prompt_text
                    return metadata, prompt
        
        # 5. As a last resort, try to find AI patterns in binary data
        if not prompt:
            bin_metadata, bin_prompt = self.extract_metadata_from_binary(file_data)
            if bin_metadata:
                metadata.update(bin_metadata)
            if bin_prompt:
                prompt = bin_prompt
                
        return metadata, prompt
    
    def extract_metadata_from_binary(self, binary_data):
        """Extract metadata from binary file data"""
        metadata = {}
        prompt = None
        
        # JSON patterns
        json_patterns = [
            rb'{"prompt":.*?}',
            rb'{"positive_prompt":.*?}',
            rb'{"data":.*?}',
            rb'{"parameters":.*?}'
        ]
        
        for pattern in json_patterns:
            matches = re.findall(pattern, binary_data)
            for match in matches:
                try:
                    json_data = json.loads(match)
                    if "prompt" in json_data:
                        metadata["Generator"] = "AI Generator (from JSON)"
                        metadata["prompt"] = json_data["prompt"]
                        prompt = json_data["prompt"]
                        return metadata, prompt
                    elif "positive_prompt" in json_data:
                        metadata["Generator"] = "AI Generator (from JSON)"
                        metadata["prompt"] = json_data["positive_prompt"]
                        prompt = json_data["positive_prompt"]
                        return metadata, prompt
                except:
                    pass
        
        # Prompt patterns
        prompt_patterns = [
            rb'"prompt"\s*:\s*"([^"]+)"',
            rb'"prompt"\s*:\s*\'([^\']+)\'',
            rb'"description"\s*:\s*"([^"]+)"',
            rb'prompt[=:]\s*([^\r\n&]+)',
            rb'Prompt:\s*([^\r\n]+)',
            rb'<prompt>(.*?)</prompt>'
        ]
        
        for pattern in prompt_patterns:
            matches = re.findall(pattern, binary_data)
            for match in matches:
                try:
                    text = match.decode('utf-8', errors='ignore')
                    # Clean up the text
                    text = re.sub(r'[^\x20-\x7E]', ' ', text).strip()
                    if len(text) > 15:  # Filter out very short matches
                        metadata["Generator"] = "AI Generator (from binary data)"
                        metadata["prompt"] = text
                        prompt = text
                        return metadata, prompt
                except:
                    pass
        
        return metadata, prompt
    
    def extract_exif_data(self, img):
        """Extract EXIF data from an image"""
        if not hasattr(img, '_getexif') or not img._getexif():
            return {}
            
        exif = img._getexif()
        processed_exif = {}
        
        for tag_id, value in exif.items():
            # Get tag name if available
            tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
            
            # Format dates if possible
            if 'Date' in tag_name and isinstance(value, str):
                try:
                    date_obj = datetime.strptime(value, '%Y:%m:%d %H:%M:%S')
                    value = date_obj.strftime('%Y-%m-%d %H:%M:%S')
                except ValueError:
                    pass
            
            # Convert byte arrays to strings where possible
            if isinstance(value, bytes):
                try:
                    value = value.decode('utf-8')
                except UnicodeDecodeError:
                    value = str(value)
            
            processed_exif[tag_name] = value
        
        return processed_exif

    def deep_scan(self):
        """Perform a deep scan for AI metadata"""
        if not self.current_file:
            self.update_status("No file loaded. Please load a file first.")
            return
        
        # Update status
        self.update_status("Performing deep scan... This may take a moment...")
        
        # Run in background thread
        threading.Thread(target=self._deep_scan_thread).start()

    def _deep_scan_thread(self):
        """Background thread for deep scanning"""
        try:
            # Read file data
            with open(self.current_file, 'rb') as f:
                file_data = f.read()
            
            # Patterns to search for
            prompt_patterns = [
                # JSON patterns
                rb'"prompt"\s*:\s*"([^"]+)"',
                rb'"prompt"\s*:\s*\'([^\']+)\'',
                rb'"description"\s*:\s*"([^"]+)"',
                rb'"text"\s*:\s*"([^"]+)"',
                rb'"positive_prompt"\s*:\s*"([^"]+)"',
                
                # Key-value patterns
                rb'prompt[=:]\s*([^\r\n&]+)',
                rb'description[=:]\s*([^\r\n&]+)',
                
                # Tagged patterns
                rb'<prompt>(.*?)</prompt>',
                rb'<description>(.*?)</description>',
                rb'Prompt:\s*([^\r\n]+)',
                rb'Generated with:\s*([^\r\n]+)',
                
                # Midjourney patterns
                rb'/imagine\s+([^\r\n]+)',
                rb'--ar \d+:\d+\s+([^\r\n]+)',
                rb'--v \d+\s+([^\r\n]+)',
                
                # Stable Diffusion patterns
                rb'Steps: \d+, Sampler: [^,]+, CFG scale: [\d\.]+, Seed: \d+',
                rb'Negative prompt:(.*?)Steps:',
                
                # Additional patterns
                rb'parameters\s*:\s*(.*?)(?:\n\n|\Z)',
                rb'DALL-E\s+\d\s+([^\r\n]+)'
            ]
            
            # Collect all potential prompts
            found_prompts = []
            
            for pattern in prompt_patterns:
                matches = re.findall(pattern, file_data)
                for match in matches:
                    try:
                        text = match.decode('utf-8', errors='ignore')
                        # Clean up the text
                        text = re.sub(r'[^\x20-\x7E]', ' ', text).strip()
                        # Deduplicate and filter very short matches
                        if len(text) > 15 and text not in [p[0] for p in found_prompts]:
                            found_prompts.append((text, len(text)))
                    except:
                        pass
            
            # Sort by length (longer texts are more likely to be actual prompts)
            found_prompts.sort(key=lambda x: x[1], reverse=True)
            
            # Update UI on main thread
            Clock.schedule_once(lambda dt: self._update_deep_scan_results(found_prompts), 0)
            
        except Exception as e:
            Clock.schedule_once(lambda dt: self.update_status(f"Deep scan error: {str(e)}"), 0)

    def _update_deep_scan_results(self, found_prompts):
        """Update UI with deep scan results"""
        if found_prompts:
            # Update prompt text area with desktop-style text editor
            self.ids.prompt_text.text = "Possible AI prompts found:\n\n"
            
            for i, (prompt, length) in enumerate(found_prompts[:10]):  # Show top 10
                self.ids.prompt_text.text += f"#{i+1} (Length: {length}):\n{prompt}\n\n"
            
            # Update AI info
            self.ids.ai_info.text = f"Deep scan found {len(found_prompts)} potential prompts"
            self.update_status(f"Deep scan complete. Found {len(found_prompts)} potential prompts.")
            
            # Save the best prompt
            if found_prompts:
                self.detected_ai_prompt = found_prompts[0][0]
        else:
            self.ids.prompt_text.text = "No potential AI prompts found in deep scan."
            self.ids.ai_info.text = "Deep scan found no AI prompts"
            self.update_status("Deep scan complete. No prompts found.")
            
        # Make sure cursor is visible
        self.ids.prompt_text.cursor = (0, 0)

    def export_metadata(self):
        """Export metadata to a JSON file"""
        if not self.current_metadata:
            self.update_status("No metadata to export. Load a file first.")
            return
        
        # Default filename is based on the original file
        if self.current_file:
            default_name = os.path.splitext(os.path.basename(self.current_file))[0] + "_metadata.json"
        else:
            default_name = "metadata.json"
        
        # Launch save dialog - but this isn't available in Kivy by default
        # In a full app, you'd implement a proper save dialog
        try:
            output_path = os.path.join(os.path.dirname(self.current_file), default_name)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(self.current_metadata, f, indent=4, default=str)
            
            self.update_status(f"Metadata exported to {output_path}")
        except Exception as e:
            self.update_status(f"Export error: {str(e)}")

    def export_prompt(self):
        """Export detected prompt to a text file"""
        if not self.detected_ai_prompt:
            self.update_status("No prompt to export. Load a file with AI prompt first.")
            return
        
        # Default filename
        if self.current_file:
            default_name = os.path.splitext(os.path.basename(self.current_file))[0] + "_prompt.txt"
        else:
            default_name = "ai_prompt.txt"
        
        try:
            output_path = os.path.join(os.path.dirname(self.current_file), default_name)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(self.detected_ai_prompt)
            
            self.update_status(f"Prompt exported to {output_path}")
        except Exception as e:
            self.update_status(f"Export error: {str(e)}")

class AIMetadataApp(App):
    def build(self):
        # Set window properties
        self.title = 'AI Media Metadata Extractor'
        Window.size = (950, 700)
        # Fix for warning in the log
        Window.minimum_width = 800
        Window.minimum_height = 600
        
        # Set dark theme colors
        Window.clearcolor = (0.1, 0.1, 0.12, 1)
        
        return MetadataDisplay()


if __name__ == '__main__':
    AIMetadataApp().run()
