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

# Try to import PIL for image processing
try:
    from PIL import Image as PILImage
    from PIL import ExifTags
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

# Define the Kivy UI
KV = '''
#:import Factory kivy.factory.Factory
#:import Window kivy.core.window.Window

<DarkLabel@Label>:
    color: 0.9, 0.9, 0.9, 1
    font_size: sp(14)
    text_size: self.width, None
    halign: 'left'
    valign: 'middle'
    padding: dp(5), dp(5)
    canvas.before:
        Color:
            rgba: 0.15, 0.15, 0.15, 1
        Rectangle:
            pos: self.pos
            size: self.size

<HeaderLabel@Label>:
    color: 0.95, 0.95, 0.95, 1
    font_size: sp(16)
    bold: True
    size_hint_y: None
    height: dp(40)
    canvas.before:
        Color:
            rgba: 0.2, 0.2, 0.25, 1
        Rectangle:
            pos: self.pos
            size: self.size

<DarkButton@Button>:
    background_color: 0.2, 0.4, 0.6, 1
    background_normal: ''
    color: 0.95, 0.95, 0.95, 1
    font_size: sp(14)
    size_hint_y: None
    height: dp(40)

<SelectableTextInput@TextInput>:
    background_color: 0.2, 0.2, 0.2, 1
    foreground_color: 0.9, 0.9, 0.9, 1
    cursor_color: 0.9, 0.9, 0.9, 1
    font_size: sp(14)
    padding: dp(10), dp(10)
    selection_color: 0.3, 0.5, 0.7, 0.5
    use_handles: True
    allow_copy: True
    
<DarkScrollView@ScrollView>:
    bar_width: dp(10)
    bar_color: 0.3, 0.4, 0.5, 0.7
    bar_inactive_color: 0.2, 0.3, 0.4, 0.5
    effect_cls: "ScrollEffect"
    scroll_type: ['bars', 'content']

<AlternatingTreeViewLabel>:
    color: 0.9, 0.9, 0.9, 1
    font_size: sp(14)
    padding: dp(5), dp(5)
    canvas.before:
        Color:
            rgba: (0.17, 0.17, 0.2, 1) if self.is_even else (0.13, 0.13, 0.15, 1)
        Rectangle:
            pos: self.pos
            size: self.size
    
<MetadataTreeView>:
    size_hint_y: None
    height: self.minimum_height
    hide_root: True
    indent_level: dp(20)
    
<MetadataDisplay>:
    orientation: 'vertical'
    spacing: dp(5)
    padding: dp(10)
    canvas.before:
        Color:
            rgba: 0.12, 0.12, 0.12, 1
        Rectangle:
            pos: self.pos
            size: self.size
            
    HeaderLabel:
        text: 'AI Media Metadata Extractor'
        
    BoxLayout:
        size_hint_y: None
        height: dp(100)
        orientation: 'vertical'
        padding: dp(10)
        spacing: dp(10)
        canvas.before:
            Color:
                rgba: 0.16, 0.16, 0.18, 1
            Rectangle:
                pos: self.pos
                size: self.size
                
        DarkLabel:
            text: 'Drag and drop files here or use the browse button'
            halign: 'center'
            
        DarkButton:
            text: 'Browse for Files'
            on_release: root.show_file_chooser()
            
    TabbedPanel:
        id: tab_panel
        do_default_tab: False
        tab_width: Window.width / 3
        background_color: 0.15, 0.15, 0.15, 1
        
        TabbedPanelItem:
            text: 'Metadata Tree'
            background_color: 0.2, 0.2, 0.25, 1
            DarkScrollView:
                id: tree_scroll
                TreeView:
                    id: metadata_tree
                    size_hint_y: None
                    height: self.minimum_height
                    hide_root: True
                    indent_level: dp(24)
                    
        TabbedPanelItem:
            text: 'AI Prompt'
            background_color: 0.2, 0.2, 0.25, 1
            BoxLayout:
                orientation: 'vertical'
                DarkScrollView:
                    SelectableTextInput:
                        id: prompt_text
                        readonly: False  # Allow text selection and copying
                        text: 'No AI prompt detected. Try using the Deep Scan button.'
                        size_hint: 1, None
                        height: max(self.minimum_height, tree_scroll.height)
                
        TabbedPanelItem:
            text: 'Raw JSON'
            background_color: 0.2, 0.2, 0.25, 1
            DarkScrollView:
                SelectableTextInput:
                    id: json_text
                    readonly: False  # Allow selection and copying
                    size_hint: 1, None
                    height: max(self.minimum_height, tree_scroll.height)
                    
    BoxLayout:
        size_hint_y: None
        height: dp(180)
        spacing: dp(10)
        
        # Left side - file preview
        BoxLayout:
            orientation: 'vertical'
            size_hint_x: 0.4
            spacing: dp(5)
            
            HeaderLabel:
                text: 'Preview'
                size_hint_y: None
                height: dp(30)
                
            Image:
                id: preview_image
                source: ''
                size_hint: None, None
                size: dp(160), dp(120)
                pos_hint: {'center_x': 0.5}
                
            DarkLabel:
                id: file_info
                text: 'No file selected'
                size_hint_y: None
                height: dp(20)
                
        # Right side - AI info and buttons
        BoxLayout:
            orientation: 'vertical'
            size_hint_x: 0.6
            spacing: dp(5)
            
            HeaderLabel:
                text: 'AI Generation Info'
                size_hint_y: None
                height: dp(30)
                
            DarkLabel:
                id: ai_info
                text: 'No AI info detected'
                size_hint_y: None
                height: dp(60)
                
            BoxLayout:
                size_hint_y: None
                height: dp(40)
                spacing: dp(10)
                
                DarkButton:
                    text: 'Deep Scan'
                    size_hint_x: 0.33
                    on_release: root.deep_scan()
                    
                DarkButton:
                    text: 'Export Metadata'
                    size_hint_x: 0.33
                    on_release: root.export_metadata()
                    
                DarkButton:
                    text: 'Export Prompt'
                    size_hint_x: 0.33
                    on_release: root.export_prompt()
                    
    DarkLabel:
        id: status_bar
        text: 'Ready - Drag files here or use Browse button'
        size_hint_y: None
        height: dp(30)
        
<LoadDialog>:
    BoxLayout:
        size: root.size
        pos: root.pos
        orientation: "vertical"
        canvas.before:
            Color:
                rgba: 0.15, 0.15, 0.15, 1
            Rectangle:
                pos: self.pos
                size: self.size
                
        FileChooserListView:
            id: filechooser
            path: root.default_path
            filters: root.filters
            canvas.before:
                Color:
                    rgba: 0.18, 0.18, 0.18, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
                    
        BoxLayout:
            size_hint_y: None
            height: dp(50)
            spacing: dp(10)
            padding: dp(10)
            
            DarkButton:
                text: "Cancel"
                on_release: root.cancel()
                
            DarkButton:
                text: "Load"
                on_release: root.load(filechooser.path, filechooser.selection)
'''

# Register the KV language string
Builder.load_string(KV)

class LoadDialog(Popup):
    load = ObjectProperty(None)
    cancel = ObjectProperty(None)
    filters = ObjectProperty(['*.png', '*.jpg', '*.jpeg', '*.webp', '*.mp4', '*.mov', '*.webm'])
    default_path = StringProperty(os.path.expanduser('~'))

class AlternatingTreeViewLabel(TreeViewLabel):
    is_even = BooleanProperty(False)

class MetadataDisplay(BoxLayout):
    def __init__(self, **kwargs):
        super(MetadataDisplay, self).__init__(**kwargs)
        self.current_file = None
        self.current_metadata = {}
        self.detected_ai_prompt = None
        self.row_count = 0  # For alternating row colors
        Window.bind(on_drop_file=self._on_drop_file)
        
    def _on_drop_file(self, window, file_path, x, y):
        """Handle dropped files"""
        # Convert bytes to string on Python 3
        if isinstance(file_path, bytes):
            file_path = file_path.decode('utf-8')
        
        # Clear previous metadata and UI before processing new file
        self.clear_data()
        
        # Process the dropped file
        self.process_file(file_path)
    
    def clear_data(self):
        """Clear all previous data and UI elements"""
        # Clear metadata storage
        self.current_metadata = {}
        self.current_file = None
        self.detected_ai_prompt = None
        
        # Clear tree view
        self.ids.metadata_tree.clear_widgets()
        
        # Clear text areas
        self.ids.prompt_text.text = "No AI prompt detected. Try using the Deep Scan button."
        self.ids.json_text.text = ""
        
        # Reset image preview
        self.ids.preview_image.source = ''
        
        # Reset info labels
        self.ids.file_info.text = "No file selected"
        self.ids.ai_info.text = "No AI info detected"
        
        # Update status
        self.update_status("Ready - Drag files here or use Browse button")
    
    def show_file_chooser(self):
        """Show file chooser dialog"""
        content = LoadDialog(
            load=self.load_file, 
            cancel=self.dismiss_popup,
            filters=['*.png', '*.jpg', '*.jpeg', '*.webp', '*.mp4', '*.mov', '*.webm']
        )
        self._popup = Popup(
            title="Load file", 
            content=content,
            size_hint=(0.9, 0.9),
            background_color=(0.2, 0.2, 0.2, 1)
        )
        self._popup.open()
    
    def load_file(self, path, selection):
        """Handle file selection from dialog"""
        if selection:
            self.dismiss_popup()
            # Clear previous data first
            self.clear_data()
            # Then process the new file
            self.process_file(selection[0])
    
    def dismiss_popup(self):
        """Close popup"""
        if hasattr(self, '_popup'):
            self._popup.dismiss()
    
    def process_file(self, file_path):
        """Process the selected file"""
        if not os.path.isfile(file_path):
            self.update_status(f"Error: Not a valid file - {file_path}")
            return
        
        # Check file extension
        _, file_ext = os.path.splitext(file_path)
        file_ext = file_ext.lower()
        
        supported_image_ext = ['.png', '.jpg', '.jpeg', '.webp']
        supported_video_ext = ['.mp4', '.mov', '.webm']
        
        if file_ext not in supported_image_ext and file_ext not in supported_video_ext:
            self.update_status(f"Error: Unsupported file type - {file_ext}")
            return
        
        # Store current file
        self.current_file = file_path
        
        # Update status
        filename = os.path.basename(file_path)
        self.update_status(f"Processing {filename}...")
        
        # Process in a separate thread to avoid UI freezing
        threading.Thread(target=self._process_file_thread, args=(file_path, file_ext)).start()
    
    def _process_file_thread(self, file_path, file_ext):
        """Background thread for file processing"""
        try:
            # Determine file type
            supported_image_ext = ['.png', '.jpg', '.jpeg', '.webp']
            supported_video_ext = ['.mp4', '.mov', '.webm']
            
            if file_ext in supported_image_ext:
                metadata, ai_prompt = self.process_image(file_path, file_ext)
            elif file_ext in supported_video_ext:
                metadata, ai_prompt = self.process_video(file_path, file_ext)
            else:
                # This shouldn't happen due to earlier check
                return
            
            # Store metadata and prompt
            self.current_metadata = metadata
            self.detected_ai_prompt = ai_prompt
            
            # Update UI on the main thread
            Clock.schedule_once(lambda dt: self.update_ui(file_path, metadata, ai_prompt), 0)
            
        except Exception as e:
            Clock.schedule_once(lambda dt: self.update_status(f"Error: {str(e)}"), 0)
    
    def update_ui(self, file_path, metadata, ai_prompt):
        """Update UI with processing results"""
        # Update file info
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        
        if file_size < 1024 * 1024:
            size_str = f"{file_size / 1024:.1f} KB"
        else:
            size_str = f"{file_size / (1024 * 1024):.2f} MB"
            
        self.ids.file_info.text = f"{filename}\n{size_str}"
        
        # Update preview image
        self.update_preview(file_path)
        
        # Update metadata tree
        self.update_metadata_tree(metadata)
        
        # Check for Midjourney prompts in Description field
        # (This is necessary since some Midjourney images store the prompt in the Format_Specific/Description field)
        if not ai_prompt and "Format_Specific" in metadata and "Description" in metadata["Format_Specific"]:
            desc = metadata["Format_Specific"]["Description"]
            if any(marker in desc for marker in ['--ar', '--v', '--style', 'Job ID:', '/imagine']):
                ai_prompt = desc
                # Add to AI_Metadata if not already there
                if "AI_Metadata" not in metadata:
                    metadata["AI_Metadata"] = {"Generator": "Midjourney", "prompt": desc}
        
        # Update AI prompt
        if ai_prompt:
            self.ids.prompt_text.text = ai_prompt
            self.detected_ai_prompt = ai_prompt
            
            # Update AI info summary
            ai_generator = metadata.get("AI_Metadata", {}).get("Generator", "Midjourney" if "--v" in ai_prompt else "Unknown AI")
            prompt_length = len(ai_prompt)
            self.ids.ai_info.text = f"Generator: {ai_generator}\nPrompt Length: {prompt_length} chars"
        else:
            self.ids.prompt_text.text = "No AI prompt detected.\nTry using the Deep Scan button."
            self.ids.ai_info.text = "No AI generation info detected"
        
        # Update JSON view - format with indentation for readability
        try:
            self.ids.json_text.text = json.dumps(metadata, indent=4, default=str)
        except Exception as e:
            self.ids.json_text.text = f"Error formatting JSON: {str(e)}"
        
        # Update status
        self.update_status(f"Loaded metadata from {filename}")
    
    def update_status(self, message):
        """Update status bar"""
        self.ids.status_bar.text = message
    
    def update_preview(self, file_path):
        """Update the preview image"""
        _, file_ext = os.path.splitext(file_path)
        file_ext = file_ext.lower()
        
        if file_ext in ['.png', '.jpg', '.jpeg', '.webp']:
            # For images, create a thumbnail
            if HAS_PIL:
                try:
                    img = PILImage.open(file_path)
                    # Create a thumbnail and save to a BytesIO object
                    img.thumbnail((160, 120))
                    buf = BytesIO()
                    img.save(buf, format='PNG')
                    buf.seek(0)
                    
                    # Create a temporary file for Kivy to load
                    temp_path = os.path.join(os.path.dirname(__file__), '_temp_thumb.png')
                    with open(temp_path, 'wb') as f:
                        f.write(buf.read())
                    
                    # Update the image source
                    self.ids.preview_image.source = temp_path
                    self.ids.preview_image.reload()
                except Exception as e:
                    print(f"Error creating thumbnail: {e}")
        else:
            # For videos, show a placeholder
            self.ids.preview_image.source = ''  # Clear the source
            
            # Schedule drawing the video placeholder
            Clock.schedule_once(self.draw_video_placeholder, 0.1)
    
    def draw_video_placeholder(self, dt):
        """Draw a placeholder for video files"""
        # Simply clear for now - in a production app you could draw a custom video icon
        pass
    
    def update_metadata_tree(self, metadata):
        """Update the metadata tree view"""
        tree = self.ids.metadata_tree
        tree.clear_widgets()
        
        # Reset row counter for alternating colors
        self.row_count = 0
        
        # Create a root node
        root = tree.add_node(TreeViewLabel(text='Root', is_open=True))
        
        # Add metadata to tree
        self._add_metadata_to_tree(tree, root, metadata)
    
    def _add_metadata_to_tree(self, tree, parent, data, key=None):
        """Recursively add metadata to tree view with alternating row colors"""
        if isinstance(data, dict):
            # If this is a root-level key or has a name
            if key is not None:
                self.row_count += 1
                node_label = AlternatingTreeViewLabel(text=key, is_open=True, is_even=(self.row_count % 2 == 0))
                node = tree.add_node(node_label, parent)
                parent = node
            
            # Add all items in the dictionary
            for k, v in sorted(data.items()):
                self._add_metadata_to_tree(tree, parent, v, k)
                
        elif isinstance(data, list):
            # Create a node for the list
            self.row_count += 1
            node_label = AlternatingTreeViewLabel(text=key, is_open=True, is_even=(self.row_count % 2 == 0))
            node = tree.add_node(node_label, parent)
            
            # Add all items in the list
            for i, item in enumerate(data):
                self._add_metadata_to_tree(tree, node, item, f"Item {i+1}")
                
        else:
            # Leaf node - just add the value
            value = str(data)
            # Limit text length to avoid very wide tree items
            if len(value) > 100:
                value = value[:97] + "..."
            
            self.row_count += 1
            node_label = AlternatingTreeViewLabel(
                text=f"{key}: {value}", 
                is_even=(self.row_count % 2 == 0)
            )
            tree.add_node(node_label, parent)
    
    def process_image(self, file_path, file_ext):
        """Process image files - extract ALL possible metadata"""
        metadata = {}
        ai_prompt = None
        
        # Basic file info
        file_size = os.path.getsize(file_path)
        metadata["Basic"] = {
            "File Name": os.path.basename(file_path),
            "File Size": f"{file_size / 1024:.1f} KB" if file_size < 1024*1024 else f"{file_size / (1024*1024):.2f} MB",
            "File Path": file_path,
            "File Extension": file_ext.upper().replace('.', '')
        }
        
        if HAS_PIL:
            try:
                # Open the image with PIL
                img = PILImage.open(file_path)
                
                # Add basic image info
                metadata["Basic"].update({
                    "Image Format": img.format,
                    "Mode": img.mode,
                    "Dimensions": f"{img.width} x {img.height} pixels",
                    "Bit Depth": str(getattr(img, 'bits', 'Unknown')),
                    "Compression": getattr(img, 'compression', 'Unknown'),
                    "Palette": "Yes" if getattr(img, 'palette', None) else "No"
                })
                
                # Extract ALL format-specific data first
                if hasattr(img, 'info'):
                    format_info = {}
                    for key, value in img.info.items():
                        if isinstance(value, (str, int, float, bool, type(None))):
                            format_info[key] = value
                        elif isinstance(value, bytes):
                            try:
                                # Try to decode bytes as UTF-8
                                decoded = value.decode('utf-8', errors='replace')
                                if len(decoded) > 100:
                                    format_info[key] = f"{decoded[:100]}... (truncated)"
                                else:
                                    format_info[key] = decoded
                            except:
                                format_info[key] = f"{str(type(value))} ({len(value)} bytes)"
                        else:
                            format_info[key] = f"{str(type(value))}"
                    
                    if format_info:
                        metadata["Format_Specific"] = format_info
                
                # Check if this is a Midjourney image based on filename patterns
                if 'Job ID:' in os.path.basename(file_path) or '_' in os.path.basename(file_path):
                    parts = os.path.basename(file_path).split('_')
                    if len(parts) >= 3:
                        # Looks like a Midjourney naming pattern
                        metadata["AI_Metadata"] = metadata.get("AI_Metadata", {})
                        metadata["AI_Metadata"]["Generator"] = "Midjourney (from filename)"
                
                # Extract AI metadata and prompt
                ai_metadata, prompt = self.extract_ai_metadata_from_image(img, file_path)
                
                if ai_metadata:
                    # Merge with any existing AI metadata
                    if "AI_Metadata" in metadata:
                        metadata["AI_Metadata"].update(ai_metadata)
                    else:
                        metadata["AI_Metadata"] = ai_metadata
                    
                if prompt:
                    ai_prompt = prompt
                
                # Extract EXIF data - get ALL possible EXIF tags
                exif_data = self.extract_exif_data(img)
                if exif_data:
                    metadata["EXIF"] = exif_data
                
                # Extract ICC Profile data if available
                if "icc_profile" in img.info:
                    try:
                        metadata["ICC_Profile"] = {"Present": "Yes", "Size": f"{len(img.info['icc_profile'])} bytes"}
                    except:
                        metadata["ICC_Profile"] = {"Present": "Yes", "Size": "Unknown"}
                
                # Extract XMP data
                if "XML:com.adobe.xmp" in img.info:
                    xmp_data = {"Present": "Yes"}
                    
                    # Try to extract key XMP fields
                    xmp_text = img.info["XML:com.adobe.xmp"]
                    xmp_data["Raw"] = xmp_text[:100] + "... (truncated)" if len(xmp_text) > 100 else xmp_text
                    
                    # Extract creator information
                    creator_match = re.search(r'<dc:creator>(.*?)</dc:creator>', xmp_text, re.DOTALL)
                    if creator_match:
                        xmp_data["Creator"] = creator_match.group(1).strip()
                    
                    # Extract description
                    desc_match = re.search(r'<dc:description>(.*?)</dc:description>', xmp_text, re.DOTALL)
                    if desc_match:
                        xmp_data["Description"] = desc_match.group(1).strip()
                    
                    # Extract rights
                    rights_match = re.search(r'<dc:rights>(.*?)</dc:rights>', xmp_text, re.DOTALL)
                    if rights_match:
                        xmp_data["Rights"] = rights_match.group(1).strip()
                    
                    # Look for AI-specific fields
                    if "trainedAlgorithmicMedia" in xmp_text:
                        xmp_data["AI_Generated"] = "Yes"
                    
                    # Extract digital source type
                    source_match = re.search(r'DigitalSourceType="([^"]+)"', xmp_text)
                    if source_match:
                        xmp_data["Digital_Source_Type"] = source_match.group(1).strip()
                    
                    # Look for GUID
                    guid_match = re.search(r'DigImageGUID="([^"]+)"', xmp_text)
                    if guid_match:
                        xmp_data["Image_GUID"] = guid_match.group(1).strip()
                    
                    metadata["XMP_Metadata"] = xmp_data
                
                # For PNG files, extract additional chunk information
                if file_ext.lower() == '.png':
                    # Use binary mode to investigate PNG chunks
                    with open(file_path, 'rb') as f:
                        f.seek(8)  # Skip PNG signature
                        
                        chunks = []
                        while True:
                            try:
                                chunk_len = struct.unpack('>I', f.read(4))[0]
                                chunk_type = f.read(4).decode('ascii')
                                
                                # Skip data but record info
                                f.seek(chunk_len, 1)  # Skip data
                                f.seek(4, 1)  # Skip CRC
                                
                                chunks.append({"Type": chunk_type, "Length": chunk_len})
                                
                                if chunk_type == 'IEND':
                                    break
                            except:
                                break
                        
                        if chunks:
                            metadata["PNG_Structure"] = {
                                "Chunk_Count": len(chunks),
                                "Chunks": chunks
                            }
            
            except Exception as e:
                metadata["Error"] = {"Processing Error": str(e)}
        
        return metadata, ai_prompt
    
    def process_video(self, file_path, file_ext):
        """Process video files"""
        metadata = {}
        ai_prompt = None
        
        # Basic file info
        file_size = os.path.getsize(file_path)
        metadata["Basic"] = {
            "File Name": os.path.basename(file_path),
            "File Size": f"{file_size / (1024*1024):.2f} MB",
            "File Path": file_path,
            "File Extension": file_ext.upper().replace('.', '')
        }
        
        # Extract video metadata
        if HAS_MEDIAINFO:
            try:
                media_info = pymediainfo.MediaInfo.parse(file_path)
                
                # Process general track
                general_track = next((track for track in media_info.tracks if track.track_type == 'General'), None)
                if general_track:
                    general_data = {}
                    for attr_name in dir(general_track):
                        if not attr_name.startswith('_') and not callable(getattr(general_track, attr_name)):
                            value = getattr(general_track, attr_name)
                            if value and not attr_name.startswith('parse_'):
                                general_data[attr_name] = value
                    metadata["General"] = general_data
                
                # Process video track
                video_track = next((track for track in media_info.tracks if track.track_type == 'Video'), None)
                if video_track:
                    video_data = {}
                    for attr_name in dir(video_track):
                        if not attr_name.startswith('_') and not callable(getattr(video_track, attr_name)):
                            value = getattr(video_track, attr_name)
                            if value and not attr_name.startswith('parse_'):
                                video_data[attr_name] = value
                    metadata["Video"] = video_data
                
                # Process audio track
                audio_track = next((track for track in media_info.tracks if track.track_type == 'Audio'), None)
                if audio_track:
                    audio_data = {}
                    for attr_name in dir(audio_track):
                        if not attr_name.startswith('_') and not callable(getattr(audio_track, attr_name)):
                            value = getattr(audio_track, attr_name)
                            if value and not attr_name.startswith('parse_'):
                                audio_data[attr_name] = value
                    metadata["Audio"] = audio_data
            
            except Exception as e:
                metadata["Error"] = {"MediaInfo Error": str(e)}
        else:
            metadata["Notice"] = {"Limited Information": "Install pymediainfo for more detailed video metadata."}
        
        # Try to extract AI metadata from binary data
        try:
            # Read the first chunk of the file to check for metadata in headers
            with open(file_path, 'rb') as f:
                # Read a large chunk to capture metadata in the header
                file_header = f.read(32768)  # 32KB should be enough for most headers
            
            # Look for JSON data or prompt patterns
            ai_metadata, prompt = self.extract_metadata_from_binary(file_header)
            
            if ai_metadata:
                metadata["AI_Metadata"] = ai_metadata
                
            if prompt:
                ai_prompt = prompt
        
        except Exception as e:
            if "Error" not in metadata:
                metadata["Error"] = {}
            metadata["Error"]["Binary Analysis Error"] = str(e)
        
        return metadata, ai_prompt
    
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
            # Update prompt text area with selectable text
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
        
        # Make sure the prompt text is editable and selectable
        self.ids.prompt_text.readonly = False
        self.ids.prompt_text.selection_color = (0.3, 0.5, 0.7, 0.5)
    
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
        Window.minimum_width, Window.minimum_height = 800, 600
        
        # Set dark theme colors
        Window.clearcolor = (0.1, 0.1, 0.12, 1)
        
        return MetadataDisplay()

if __name__ == '__main__':
    AIMetadataApp().run()