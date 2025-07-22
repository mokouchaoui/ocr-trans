#!/usr/bin/env python3

"""
OCR System Test and Initialization Script
Tests the custom OCR implementation and validates the system setup
"""

import sys
import os
import traceback
from pathlib import Path

def test_ocr_imports():
    """Test if we can import our custom OCR module"""
    try:
        from custom_ocr import CustomOCR
        print("✅ Successfully imported CustomOCR")
        return True
    except ImportError as e:
        print(f"❌ Failed to import CustomOCR: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error importing CustomOCR: {e}")
        return False

def test_ocr_initialization():
    """Test if we can initialize the OCR system"""
    try:
        from custom_ocr import CustomOCR
        ocr = CustomOCR()
        print("✅ Successfully initialized CustomOCR")
        return True, ocr
    except Exception as e:
        print(f"❌ Failed to initialize CustomOCR: {e}")
        traceback.print_exc()
        return False, None

def test_tesseract_availability():
    """Test if Tesseract is available"""
    import subprocess
    try:
        result = subprocess.run(['tesseract', '--version'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            version_info = result.stdout.split('\n')[0]
            print(f"✅ Tesseract available: {version_info}")
            return True
        else:
            print(f"❌ Tesseract command failed: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print("❌ Tesseract command timed out")
        return False
    except FileNotFoundError:
        print("❌ Tesseract command not found")
        return False
    except Exception as e:
        print(f"❌ Error testing Tesseract: {e}")
        return False

def test_c_library():
    """Test if the C OCR library is available"""
    try:
        # Check if the shared library exists
        lib_paths = [
            '/usr/local/lib/libcustom_ocr.so',
            './libcustom_ocr.so',
            'libcustom_ocr.so'
        ]
        
        for lib_path in lib_paths:
            if os.path.exists(lib_path):
                print(f"✅ Found C OCR library at: {lib_path}")
                return True
        
        print("❌ C OCR library not found in expected locations")
        print("Available files in current directory:")
        for file in os.listdir('.'):
            if 'ocr' in file.lower() or file.endswith('.so'):
                print(f"  - {file}")
        return False
        
    except Exception as e:
        print(f"❌ Error checking C library: {e}")
        return False

def test_llama_api():
    """Test if the Llama API is available"""
    try:
        import requests
        
        llama_url = "http://38.46.220.18:5000/api/ask"
        test_data = {
            "message": "Hello, this is a test message."
        }
        
        print(f"🔍 Testing Llama API at {llama_url}...")
        
        response = requests.post(llama_url, json=test_data, timeout=10)
        
        if response.status_code == 200:
            print("✅ Llama API is responding")
            result = response.json()
            print(f"API Response preview: {str(result)[:100]}...")
            return True
        else:
            print(f"❌ Llama API returned status code: {response.status_code}")
            return False
            
    except requests.exceptions.ConnectTimeout:
        print("❌ Llama API connection timeout")
        return False
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to Llama API")
        return False
    except Exception as e:
        print(f"❌ Error testing Llama API: {e}")
        return False

def test_required_packages():
    """Test if all required packages are available"""
    required_packages = [
        'fastapi',
        'uvicorn',
        'pillow',
        'pdf2image',
        'requests',
        'mysql.connector'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            if package == 'mysql.connector':
                import mysql.connector
            elif package == 'pillow':
                from PIL import Image
            elif package == 'pdf2image':
                from pdf2image import convert_from_bytes
            else:
                __import__(package)
            
            print(f"✅ {package} is available")
        except ImportError:
            print(f"❌ {package} is missing")
            missing_packages.append(package)
    
    return len(missing_packages) == 0

def run_comprehensive_test():
    """Run all tests and report system status"""
    print("🧪 Running OCR System Tests...")
    print("=" * 50)
    
    tests = [
        ("Required Packages", test_required_packages),
        ("Tesseract OCR", test_tesseract_availability),
        ("C OCR Library", test_c_library),
        ("Custom OCR Import", test_ocr_imports),
        ("Custom OCR Init", lambda: test_ocr_initialization()[0]),
        ("Llama API", test_llama_api),
    ]
    
    results = {}
    all_passed = True
    
    for test_name, test_func in tests:
        print(f"\n🔍 Testing {test_name}...")
        try:
            result = test_func()
            results[test_name] = result
            if not result:
                all_passed = False
        except Exception as e:
            print(f"❌ Test {test_name} failed with exception: {e}")
            results[test_name] = False
            all_passed = False
    
    print("\n" + "=" * 50)
    print("📊 Test Results Summary:")
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {test_name}: {status}")
    
    print("\n" + "=" * 50)
    if all_passed:
        print("🎉 All tests passed! OCR system is ready.")
        return True
    else:
        print("⚠️ Some tests failed. Please check the issues above.")
        return False

if __name__ == "__main__":
    success = run_comprehensive_test()
    sys.exit(0 if success else 1)
