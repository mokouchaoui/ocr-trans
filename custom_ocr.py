"""
Python wrapper for C-based OCR using ctypes
This module provides a Python interface to the custom C OCR library
"""

import os
import ctypes
from ctypes import c_char_p, c_void_p, c_size_t, c_float
import tempfile
from typing import Optional, Tuple
import subprocess
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class COCRWrapper:
    """Python wrapper for C-based OCR library"""
    
    def __init__(self, library_path: str = None):
        """
        Initialize the C OCR wrapper
        
        Args:
            library_path: Path to the compiled OCR library (.so or .dll)
        """
        if library_path is None:
            # Try to find the library in the current directory
            current_dir = os.path.dirname(os.path.abspath(__file__))
            if os.name == 'nt':  # Windows
                library_path = os.path.join(current_dir, 'libocr.dll')
            else:  # Linux/macOS
                library_path = os.path.join(current_dir, 'libocr.so')
        
        try:
            self.lib = ctypes.CDLL(library_path)
            self._setup_function_signatures()
            logger.info(f"✅ Loaded OCR library: {library_path}")
        except OSError as e:
            logger.error(f"❌ Failed to load OCR library: {e}")
            raise
    
    def _setup_function_signatures(self):
        """Setup function signatures for the C library"""
        # ocr_process_file(const char* file_path, const char* language)
        self.lib.ocr_process_file.argtypes = [c_char_p, c_char_p]
        self.lib.ocr_process_file.restype = c_char_p
        
        # ocr_process_memory(const unsigned char* data, size_t size, const char* language)
        self.lib.ocr_process_memory.argtypes = [ctypes.POINTER(ctypes.c_ubyte), c_size_t, c_char_p]
        self.lib.ocr_process_memory.restype = c_char_p
        
        # ocr_get_confidence(const char* file_path, const char* language)
        self.lib.ocr_get_confidence.argtypes = [c_char_p, c_char_p]
        self.lib.ocr_get_confidence.restype = c_float
        
        # ocr_free_text(char* text)
        self.lib.ocr_free_text.argtypes = [c_char_p]
        self.lib.ocr_free_text.restype = None
    
    def extract_text_from_file(self, file_path: str, language: str = "fra+eng") -> Tuple[str, float]:
        """
        Extract text from an image file
        
        Args:
            file_path: Path to the image file
            language: Language codes (e.g., "fra+eng" for French+English)
            
        Returns:
            Tuple of (extracted_text, confidence_score)
        """
        try:
            # Convert strings to bytes for C function
            file_path_bytes = file_path.encode('utf-8')
            language_bytes = language.encode('utf-8')
            
            # Call C function
            result_ptr = self.lib.ocr_process_file(file_path_bytes, language_bytes)
            
            if result_ptr:
                # Convert C string to Python string
                text = result_ptr.decode('utf-8')
                
                # Get confidence score
                confidence = self.lib.ocr_get_confidence(file_path_bytes, language_bytes)
                
                # Free C memory
                self.lib.ocr_free_text(result_ptr)
                
                logger.info(f"✅ OCR completed for {file_path}: {len(text)} characters, {confidence:.1f}% confidence")
                return text, float(confidence)
            else:
                logger.error(f"❌ OCR failed for {file_path}")
                return "", 0.0
                
        except Exception as e:
            logger.error(f"❌ Error in OCR processing: {e}")
            return "", 0.0
    
    def extract_text_from_memory(self, image_data: bytes, language: str = "fra+eng") -> Tuple[str, float]:
        """
        Extract text from image data in memory
        
        Args:
            image_data: Raw image data as bytes
            language: Language codes
            
        Returns:
            Tuple of (extracted_text, confidence_score)
        """
        try:
            # Convert bytes to ctypes array
            data_array = (ctypes.c_ubyte * len(image_data)).from_buffer_copy(image_data)
            language_bytes = language.encode('utf-8')
            
            # Call C function
            result_ptr = self.lib.ocr_process_memory(data_array, len(image_data), language_bytes)
            
            if result_ptr:
                text = result_ptr.decode('utf-8')
                self.lib.ocr_free_text(result_ptr)
                
                logger.info(f"✅ OCR completed from memory: {len(text)} characters")
                return text, 95.0  # Assume good confidence for memory processing
            else:
                logger.error("❌ OCR failed for memory data")
                return "", 0.0
                
        except Exception as e:
            logger.error(f"❌ Error in memory OCR processing: {e}")
            return "", 0.0


class OCRFallback:
    """Fallback OCR using command-line tesseract"""
    
    def __init__(self):
        """Initialize fallback OCR"""
        self.tesseract_available = self._check_tesseract()
        if self.tesseract_available:
            logger.info("✅ Tesseract CLI available as fallback")
        else:
            logger.warning("⚠️ Tesseract CLI not available")
    
    def _check_tesseract(self) -> bool:
        """Check if tesseract command is available"""
        try:
            result = subprocess.run(['tesseract', '--version'], 
                                  capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def extract_text_from_file(self, file_path: str, language: str = "fra+eng") -> Tuple[str, float]:
        """
        Extract text using command-line tesseract
        
        Args:
            file_path: Path to the image file
            language: Language codes
            
        Returns:
            Tuple of (extracted_text, confidence_score)
        """
        if not self.tesseract_available:
            logger.error("❌ Tesseract CLI not available")
            return "", 0.0
        
        try:
            # Create temporary file for output
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.txt', delete=False) as temp_file:
                temp_output = temp_file.name
            
            # Run tesseract
            cmd = [
                'tesseract', 
                file_path, 
                temp_output.replace('.txt', ''),  # tesseract adds .txt automatically
                '-l', language,
                '--psm', '6',  # Uniform block of text
                '--oem', '3'   # Default OCR Engine Mode
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                # Read the output
                with open(temp_output, 'r', encoding='utf-8') as f:
                    text = f.read()
                
                # Clean up
                os.unlink(temp_output)
                
                logger.info(f"✅ Fallback OCR completed: {len(text)} characters")
                return text, 85.0  # Assume reasonable confidence
            else:
                logger.error(f"❌ Tesseract failed: {result.stderr}")
                return "", 0.0
                
        except Exception as e:
            logger.error(f"❌ Error in fallback OCR: {e}")
            return "", 0.0


class CustomOCR:
    """Main OCR class that tries C library first, then falls back to CLI"""
    
    def __init__(self):
        """Initialize OCR with automatic fallback"""
        self.c_ocr = None
        self.fallback_ocr = OCRFallback()
        
        # Try to load C library
        try:
            self.c_ocr = COCRWrapper()
            logger.info("🚀 Using C-based OCR library")
        except Exception as e:
            logger.warning(f"⚠️ C OCR library not available: {e}")
            logger.info("🔄 Will use fallback OCR")
    
    def extract_text(self, file_path: str = None, image_data: bytes = None, 
                    language: str = "fra+eng") -> Tuple[str, float]:
        """
        Extract text from image file or data
        
        Args:
            file_path: Path to image file (if processing file)
            image_data: Raw image data (if processing from memory)
            language: Language codes for OCR
            
        Returns:
            Tuple of (extracted_text, confidence_score)
        """
        # Try C library first
        if self.c_ocr:
            try:
                if file_path:
                    return self.c_ocr.extract_text_from_file(file_path, language)
                elif image_data:
                    return self.c_ocr.extract_text_from_memory(image_data, language)
            except Exception as e:
                logger.warning(f"⚠️ C OCR failed, trying fallback: {e}")
        
        # Fallback to CLI tesseract
        if file_path and self.fallback_ocr.tesseract_available:
            return self.fallback_ocr.extract_text_from_file(file_path, language)
        elif image_data:
            # For memory data, save to temp file first
            with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as temp_file:
                temp_file.write(image_data)
                temp_path = temp_file.name
            
            try:
                result = self.fallback_ocr.extract_text_from_file(temp_path, language)
                os.unlink(temp_path)
                return result
            except Exception as e:
                logger.error(f"❌ All OCR methods failed: {e}")
                return "", 0.0
        
        logger.error("❌ No OCR method available")
        return "", 0.0


# Test function
def test_ocr():
    """Test the OCR functionality"""
    print("🧪 Testing Custom OCR Implementation...")
    
    ocr = CustomOCR()
    
    # Test with a sample file if available
    test_files = ['test_image.png', 'sample.pdf', 'invoice.jpg']
    
    for test_file in test_files:
        if os.path.exists(test_file):
            print(f"\n📄 Testing with {test_file}:")
            text, confidence = ocr.extract_text(file_path=test_file)
            print(f"📝 Extracted text: {text[:200]}...")
            print(f"📊 Confidence: {confidence:.1f}%")
            break
    else:
        print("⚠️ No test files found. Place an image file for testing.")


if __name__ == "__main__":
    test_ocr()
