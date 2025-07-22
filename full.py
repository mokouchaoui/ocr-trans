import os
import json
import re
import requests
import subprocess
import mysql.connector
import datetime
import glob
import time
from pdf2image import convert_from_bytes
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from jinja2 import Template
from tempfile import NamedTemporaryFile
import uvicorn
import asyncio
import PIL 
from PIL import Image
import io

# Import custom OCR
from custom_ocr import CustomOCR

# Try to import demjson3, but handle gracefully if not available
try:
    import demjson3
    DEMJSON3_AVAILABLE = True
except ImportError:
    DEMJSON3_AVAILABLE = False
    print("⚠️ demjson3 not available - will use standard JSON parser")

# Initialize custom OCR
print("🔧 Initializing Custom OCR...")
custom_ocr = CustomOCR()

# Set the path to your downloaded key for Google Cloud (now optional/backup)
if os.path.exists("key.json"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "key.json"
    print("✅ Google Cloud credentials found (backup)")
else:
    print("⚠️ Google Cloud credentials not found - using custom OCR only")

def clean_text(text):
    """Clean OCR text by fixing common character encoding issues and preserving structure"""
    # Dictionary of common OCR character replacements
    replacements = {
        'Num�ro': 'Numéro',
        'R�f�rence': 'Référence', 
        'D�signation': 'Désignation',
        'Qt�': 'Qté',
        'Unit�': 'Unité',
        'Pi�ce': 'Pièce',
        'r�glement': 'règlement',
        '�ch�ance': 'échéance',
        'Arr�t�e': 'Arrêtée',
        'pr�sente': 'présente',
        '�tage': 'étage',
        'T�l': 'Tél',
        'Cr�dit': 'Crédit',
        'p�nalit�': 'pénalité',
        'd�lais': 'délais',
        'R�gularit�': 'Régularité',
        '�': 'é',  # Generic replacement for most cases
        # Add OCR-specific fixes for totals
        'TOTAI': 'TOTAL',  # Common OCR error
        'TOTALI': 'TOTAL',
        'TQTAL': 'TOTAL',
        'Montant TTC': 'TOTAL TTC',  # Convert "Montant TTC" to "TOTAL TTC"
        'Montant HT': 'TOTAL HT',    # Convert "Montant HT" to "TOTAL HT"
    }
    
    # Apply replacements
    cleaned_text = text
    for old, new in replacements.items():
        cleaned_text = cleaned_text.replace(old, new)
    
    # PRESERVE STRUCTURE: Add line breaks for ALL invoice sections
    structure_patterns = [
        # Invoice header sections
        (r'(\s)(Facture)', r'\1\n\2'),  # New line before "Facture"
        (r'(\s)(FACTURE)', r'\1\n\2'),  # New line before "FACTURE"
        (r'(\s)(N°)', r'\1\n\2'),       # New line before "N°"
        (r'(\s)(Numéro)', r'\1\n\2'),   # New line before "Numéro"
        (r'(\s)(Date)', r'\1\n\2'),     # New line before "Date"
        (r'(\s)(Référence)', r'\1\n\2'), # New line before "Référence"
        
        # Company and address sections
        (r'(\s)(INTEGRATEUR)', r'\1\n\2'), # New line before company info
        (r'(\s)(Zone Franche)', r'\1\n\2'), # New line before address
        (r'(\s)(I\.C\.E)', r'\1\n\2'),   # New line before ICE
        (r'(\s)(RC)', r'\1\n\2'),        # New line before RC
        (r'(\s)(Tél)', r'\1\n\2'),       # New line before Tel
        
        # Table headers and item sections
        (r'(\s)(Désignation)', r'\1\n\2'), # New line before "Désignation"
        (r'(\s)(Qté)', r'\1\n\2'),       # New line before "Qté"
        (r'(\s)(Unité)', r'\1\n\2'),     # New line before "Unité"
        (r'(\s)(Prix unitaire)', r'\1\n\2'), # New line before "Prix unitaire"
        (r'(\s)(Pièce)', r'\1\n\2'),     # New line before "Pièce"
        (r'(\s)(Mètre)', r'\1\n\2'),     # New line before "Mètre"
        
        # Product codes and descriptions
        (r'(\s)(STRUCTURE-)', r'\1\n\2'), # New line before product lines
        (r'(\s)(HABILLAGE-)', r'\1\n\2'), # New line before product lines
        (r'(\s)(PANNEAU-)', r'\1\n\2'),  # New line before product lines
        (r'(\s)(LED-)', r'\1\n\2'),      # New line before product lines
        (r'(\s)(BARDAGE-)', r'\1\n\2'),  # New line before product lines
        (r'(\s)(POSE-)', r'\1\n\2'),     # New line before product lines
        
        # Amounts and totals
        (r'(\s)(TOTAL)', r'\1\n\2'),    # New line before "TOTAL"
        (r'(\s)(Total)', r'\1\n\2'),    # New line before "Total"
        (r'(\s)(Montant)', r'\1\n\2'),  # New line before "Montant"
        (r'(\s)(NET À PAYER)', r'\1\n\2'), # New line before "NET À PAYER"
        (r'(\s)(À PAYER)', r'\1\n\2'),  # New line before "À PAYER"
        (r'(\s)(Mode)', r'\1\n\2'),     # New line before "Mode réglement"
        (r'(\s)(Chèque)', r'\1\n\2'),   # New line before payment method
        
        # Numerical patterns for amounts
        (r'(\d{1,3}[,\.]\d{2,3}[,\.]\d{2})', r'\n\1'),  # New line before large amounts like 180.894,20
        (r'(\d{1,6}[,\.]\d{2})\s*(?=\d{1,6}[,\.]\d{2})', r'\1\n'),  # Separate consecutive amounts
        
        # Currency amounts - separate each amount on its own line
        (r'(\d{1,6}[,\.]\d{2})\s*(EUR|DH|MAD|USD|\$)', r'\n\1 \2'),
        (r'(EUR|DH|MAD|USD|\$)\s*(\d{1,6}[,\.]\d{2})', r'\n\1 \2'),
        
        # Item separators - add line breaks between product items
        (r'(\d{1,2},\d{2})\s+([A-Z][A-Z-]+)', r'\1\n\2'),  # Amount followed by product code
        (r'([A-Z-]+)\s+([A-Z][A-Z\s]+[0-9])', r'\1\n\2'),  # Product code followed by description
        
        # Date patterns
        (r'(\d{2}/\d{2}/\d{4})', r'\n\1'),  # Separate dates
        
        # Footer sections
        (r'(\s)(Arrêtée)', r'\1\n\2'),   # New line before "Arrêtée"
        (r'(\s)(Une pénalité)', r'\1\n\2'), # New line before penalty text
    ]
    
    # Apply structure patterns
    for pattern, replacement in structure_patterns:
        cleaned_text = re.sub(pattern, replacement, cleaned_text, flags=re.IGNORECASE)
    
    # ADDITIONAL STRUCTURING: Separate invoice items properly
    # Pattern to separate item lines: Code + Description + Qty + Unit + Price + Amount
    item_separation_patterns = [
        # Separate items with amounts at the end of line
        (r'([0-9,\.]+)\s+([A-Z][A-Z-]{2,}[-\s])', r'\1\n\2'),  # Amount followed by product code
        (r'([A-Z-]+\s+[A-Z\s]+)\s+(\d+,?\d*)\s+(Pièce|Mètre)', r'\1\n\2 \3'),  # Description + Qty + Unit
        (r'(Pièce|Mètre)\s+([0-9,\.]+)', r'\1\n\2'),  # Unit followed by amount
        
        # Separate consecutive product codes/descriptions
        (r'([0-9,\.]{3,})\s+([A-Z]{2,}[-\s])', r'\1\n\2'),  # Amount + Product code
        (r'([A-Z-]{4,})\s+([A-Z][A-Z\s]{5,})', r'\1\n\2'),  # Code + Description
        
        # Separate table data properly
        (r'(\d+,\d{2})\s+(\d+,\d{2})', r'\1\n\2'),  # Separate consecutive amounts
        (r'([0-9]{1,3},\d{2})\s+([0-9]{1,3},\d{2})', r'\1\n\2'),  # Small amounts
        (r'([0-9]{1,6}\.\d{3},\d{2})', r'\n\1'),  # Large formatted amounts
        
        # Improve spacing around key invoice elements
        (r'([A-Z]{2}[0-9]{6})', r'\n\1'),  # Invoice numbers like FA009421
        (r'(0[0-9]/[0-9]{2}/[0-9]{4})', r'\n\1'),  # Dates
    ]
    
    # Apply additional item separation
    for pattern, replacement in item_separation_patterns:
        cleaned_text = re.sub(pattern, replacement, cleaned_text, flags=re.IGNORECASE)
    
    # Fix common number formatting issues (but preserve line breaks)
    cleaned_text = re.sub(r'(\d)\s+(\d)', r'\1\2', cleaned_text)  # Remove spaces between digits
    cleaned_text = re.sub(r'([0-9])\s*([,.])\s*([0-9])', r'\1\2\3', cleaned_text)  # Fix "123 . 45" to "123.45"
    
    # Clean up excessive whitespace but preserve line breaks
    cleaned_text = re.sub(r'[ \t]+', ' ', cleaned_text)  # Replace multiple spaces/tabs with single space
    cleaned_text = re.sub(r'\n\s*\n', '\n', cleaned_text)  # Remove empty lines
    cleaned_text = cleaned_text.strip()
    
    # FINAL STRUCTURING: Create a truly line-by-line format
    lines = cleaned_text.split('\n')
    structured_lines = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Further split lines that contain multiple data elements
        # Split on multiple spaces (indicating separate columns)
        if re.search(r'\s{3,}', line):  # 3+ consecutive spaces
            parts = re.split(r'\s{3,}', line)
            for part in parts:
                if part.strip():
                    structured_lines.append(part.strip())
        else:
            structured_lines.append(line)
    
    # Join back with newlines for better structure
    final_text = '\n'.join(structured_lines)
    
    print(f"🔧 Text structure improved - converted to {len(structured_lines)} structured lines")
    return final_text

def extract_text_with_custom_ocr(file_content, filename):
    """Extract text from image/PDF using custom C-based OCR"""
    try:
        # Check if the file is a PDF
        if filename.lower().endswith('.pdf'):
            print("🔄 Converting PDF to images...")
            try:
                # Convert PDF to images
                images = convert_from_bytes(file_content, dpi=300, fmt='PNG')
                print(f"📄 PDF converted to {len(images)} image(s)")
                
                all_text = []
                
                # Process each page/image
                for i, img in enumerate(images):
                    print(f"🔍 Processing page {i+1}/{len(images)}...")
                    
                    # Convert PIL image to bytes
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format='PNG')
                    img_bytes = img_byte_arr.getvalue()
                    
                    # Save temp image file for OCR processing
                    temp_filename = f"temp_page_{i+1}.png"
                    with open(temp_filename, 'wb') as temp_file:
                        temp_file.write(img_bytes)
                    
                    try:
                        # Process with custom OCR
                        page_text = custom_ocr.extract_text(temp_filename)
                        if page_text and page_text.strip():
                            all_text.append(page_text)
                            print(f"✅ Extracted text from page {i+1}: {len(page_text)} characters")
                        else:
                            print(f"⚠️ No text found on page {i+1}")
                    finally:
                        # Clean up temp file
                        if os.path.exists(temp_filename):
                            os.remove(temp_filename)
                
                if not all_text:
                    return "No text found in PDF."
                
                # Combine all pages text
                raw_text = "\n\n--- PAGE BREAK ---\n\n".join(all_text)
                
            except Exception as pdf_error:
                print(f"❌ PDF conversion error: {pdf_error}")
                raise Exception(f"Failed to convert PDF to images: {str(pdf_error)}")
        
        else:
            # Handle image files directly
            print("🔍 Processing image file...")
            
            # Save temp image file for OCR processing
            temp_filename = f"temp_image_{int(time.time())}.{filename.split('.')[-1]}"
            with open(temp_filename, 'wb') as temp_file:
                temp_file.write(file_content)
            
            try:
                # Process with custom OCR
                raw_text = custom_ocr.extract_text(temp_filename)
                if not raw_text or not raw_text.strip():
                    return "No text found."
            finally:
                # Clean up temp file
                if os.path.exists(temp_filename):
                    os.remove(temp_filename)
        
        # Clean the extracted text
        cleaned_text = clean_text(raw_text)
        
        print(f"🔍 OCR detected text: {len(cleaned_text)} characters")
        print("📄 Text preview (first 500 chars):", cleaned_text[:500])
        
        # Save structured text to file for debugging
        save_extracted_text_to_file(cleaned_text, "structured_invoice.txt")
        
        # Also save the original raw text for comparison
        save_extracted_text_to_file(raw_text, "original_ocr_output.txt")
        
        return cleaned_text
        
    except Exception as e:
        print(f"❌ Custom OCR error: {e}")
        raise Exception(f"Custom OCR failed: {str(e)}")

def save_extracted_text_to_file(text, filename="output.txt"):
    """Save extracted text to file for debugging with line count info"""
    try:
        with open(filename, "w", encoding="utf-8") as file:
            file.write(text)
        
        # Count lines for debugging info
        line_count = len(text.split('\n'))
        char_count = len(text)
        
        print(f"💾 Extracted text saved to {filename}")
        print(f"📊 File contains {line_count} lines and {char_count} characters")
        
        # Show first few lines as preview
        lines = text.split('\n')[:5]  # First 5 lines
        print("📄 First few lines preview:")
        for i, line in enumerate(lines, 1):
            print(f"   {i}. {line[:80]}{'...' if len(line) > 80 else ''}")
            
    except Exception as e:
        print(f"⚠️ Failed to save text to file: {e}")

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Get list of dossiers for dropdown
def get_dossiers():
    try:
        print("🔍 Attempting to connect to database for dossiers...")
        conn = mysql.connector.connect(
            host='mysql-4791ff0-mohamed-cfcb.c.aivencloud.com',
            port=28974,
            user='avnadmin',
            password='AVNS_awY4JgPDS6TiUUadqdu',
            database='wdoptitransit_khaladi',
            connection_timeout=10
        )
        cursor = conn.cursor()
        print("✅ Connected to database successfully")
        
        # Check if table exists first
        cursor.execute("SHOW TABLES LIKE 'm_dossier'")
        table_exists = cursor.fetchone()
        print(f"🔍 Table m_dossier exists: {table_exists is not None}")
        
        if table_exists:
            # Filter for 2025 dossiers only (starting with "I25") and limit to reasonable number
            cursor.execute("SELECT M_Ds_Num FROM m_dossier WHERE M_Ds_Num LIKE 'I25%' ORDER BY M_Ds_Num DESC LIMIT 50")
            results = cursor.fetchall()
            dossiers = [row[0] for row in results if row[0] is not None]
            print(f"✅ Found {len(dossiers)} dossiers for 2025: {dossiers[:5]}...")  # Show first 5
        else:
            print("❌ Table m_dossier not found")
            dossiers = []
            
        cursor.close()
        conn.close()
        return dossiers
    except mysql.connector.Error as e:
        print(f"❌ Failed to fetch dossiers: {e}")
        return []
    except Exception as e:
        print(f"❌ Unexpected error fetching dossiers: {e}")
        return []

# DB Connection with fallback
def save_to_db(data, dossier_num=None):
    # Try remote database first
    try:
        print("🔗 Attempting to connect to remote database...")
        conn = mysql.connector.connect(
            host='mysql-4791ff0-mohamed-cfcb.c.aivencloud.com',
            port=28974,
            user='avnadmin',
            password='AVNS_awY4JgPDS6TiUUadqdu',
            database='wdoptitransit_khaladi',
            connection_timeout=10,  # Add timeout
            autocommit=True
        )
        cursor = conn.cursor()
        print("✅ Connected to remote database successfully!")
    except mysql.connector.Error as e:
        print(f"❌ Remote database connection failed: {e}")
        print("💾 Saving data to local JSON file as fallback...")
        
        # Fallback: Save to local JSON file
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"invoice_data_{timestamp}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Data saved to local file: {filename}")
        return  # Exit function early
    
    # If we get here, database connection was successful
    cursor = conn.cursor()

    invoice_sql = """
    INSERT INTO invoices (M_fe_num, M_fe_date, M_fe_Pnet, M_fe_Pbrute, M_fe_valDev, dossier_num)
    VALUES (%s, %s, %s, %s, %s, %s)
    """
    invoice_values = (
        data["M_fe_num"],
        data["M_fe_date"],  # store as string
        data["M_fe_Pnet"],
        data["M_fe_Pbrute"],
        data["M_fe_valDev"],
        dossier_num
    )
    cursor.execute(invoice_sql, invoice_values)
    invoice_id = cursor.lastrowid

    item_sql = """
    INSERT INTO invoice_items (
        invoice_id, AvecSansPaiment, M_fl_Ngp, M_fl_art, M_fl_desig, M_fl_orig,
        quantity, M_fl_unite, M_fl_PNet, M_fl_PBrut, M_fl_valDev
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    for item in data["items"]:
        item_values = (
            invoice_id,
            item.get("AvecSansPaiment", ""),
            item.get("M_fl_Ngp", ""),
            item.get("M_fl_art", ""),
            item.get("M_fl_desig", ""),
            item.get("M_fl_orig", ""),
            item.get("quantity", 0),
            item.get("M_fl_unite", ""),
            item.get("M_fl_PNet", ""),
            item.get("M_fl_PBrut", 0.0),
            item.get("M_fl_valDev", 0.0)
        )
        cursor.execute(item_sql, item_values)

    conn.commit()
    cursor.close()
    conn.close()

# Extract potential invoice metadata from OCR text
def extract_invoice_metadata(text):
    """
    Extract potential invoice number and date patterns from OCR text, specialized for French invoices
    """
    import datetime
    
    metadata = {
        "potential_invoice_numbers": [],
        "potential_dates": [],
        "potential_weights": [],
        "potential_totals": [],
        "potential_currencies": [],
        "text_preview": text[:500] if text else ""
    }
    
    # Look for French invoice number patterns
    invoice_patterns = [
        r'FACTURE N°?\s*:?\s*(\d+)',  # FACTURE N° : 832
        r'N°\s*:?\s*(\d+)',  # N° : 832
        r'(?:invoice|facture|n[°o]\.?\s*(?:invoice|facture)?)\s*[:\-]?\s*([A-Z0-9\-\/]+)',
        r'(?:inv|fact)\s*[:\-]?\s*([A-Z0-9\-\/]+)',
        r'([A-Z]{2,}\d{3,})',  # General pattern like ABC123456
        r'(\d{3,})',  # Numbers with 3+ digits
    ]
    
    for pattern in invoice_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        metadata["potential_invoice_numbers"].extend(matches)
    
    # Look for French date patterns
    date_patterns = [
        r'LE\s+(\d{1,2}[-\/]\d{1,2}[-\/]\d{2,4})',  # LE 11-04-2025
        r'(\d{1,2}[-\/]\d{1,2}[-\/]\d{2,4})',  # DD-MM-YYYY or DD/MM/YYYY
        r'(\d{2,4}[-\/]\d{1,2}[-\/]\d{1,2})',  # YYYY-MM-DD
        r'(\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+\d{2,4})',  # French dates
    ]
    
    for pattern in date_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        metadata["potential_dates"].extend(matches)
    
    # Look for weight patterns
    weight_patterns = [
        r'Poids\s+Brut\s*:?\s*([\d,\.]+)\s*KGS?',  # Poids Brut : 8,025 KGS
        r'Poids\s+Net\s*:?\s*([\d,\.]+)\s*KGS?',   # Poids Net : 6,825 KGS
        r'([\d,\.]+)\s*KGS?',  # Any weight in KGS
    ]
    
    for pattern in weight_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        metadata["potential_weights"].extend(matches)
    
    # Look for total patterns and monetary values (more specific patterns first)
    total_patterns = [
        # Enhanced patterns for your invoice format
        r'Montant\s*TTC\s*[:\s]*([0-9]{1,6}[,\.]\d{2})',  # Montant TTC 180.894,20
        r'TOTAL\s*TTC\s*[:\s]*([0-9]{1,6}[,\.]\d{2})',    # TOTAL TTC 180.894,20
        r'Montant\s*HT\s*[:\s]*([0-9]{1,6}[,\.]\d{2})',   # Montant HT 180.894,20
        r'TOTAL\s*HT\s*[:\s]*([0-9]{1,6}[,\.]\d{2})',     # TOTAL HT 180.894,20
        r'TOTAL\s*[:\s]+([0-9]{1,6}[,\.]\d{2})',          # TOTAL : 255.50 or TOTAL 255,50
        r'Total\s*[:\s]+([0-9]{1,6}[,\.]\d{2})',          # Total : 255.50 or Total 255,50
        r'MONTANT\s*TOTAL\s*[:\s]*([0-9]{1,6}[,\.]\d{2})', # MONTANT TOTAL : 255.50
        r'Montant\s*Total\s*[:\s]*([0-9]{1,6}[,\.]\d{2})', # Montant Total : 255.50
        r'SOUS\s*TOTAL\s*[:\s]*([0-9]{1,6}[,\.]\d{2})',   # SOUS TOTAL : 255.50
        r'NET\s*À\s*PAYER\s*[:\s]*([0-9]{1,6}[,\.]\d{2})', # NET À PAYER : 255.50
        r'À\s*PAYER\s*[:\s]*([0-9]{1,6}[,\.]\d{2})',      # À PAYER : 255.50
        r'Prix\s*total\s*[:\s]*([0-9]{1,6}[,\.]\d{2})',   # Prix total : 255.50
        r'Valeur\s*totale\s*[:\s]*([0-9]{1,6}[,\.]\d{2})', # Valeur totale : 255.50
        r'Valeur\s*Totale\s*[:\s]*([0-9]{1,6}[,\.]\d{2})', # Valeur Totale : 255.50
        r'Valeur\s*devise\s*[:\s]*([0-9]{1,6}[,\.]\d{2})', # Valeur devise : 255.50
        # Patterns for amounts at end of lines (common in invoices)
        r'([0-9]{3,6}[,\.]\d{2})\s*(?:DH|EUR|€|MAD|USD|\$)\s*$',  # Amount before currency at end of line
        r'(?:DH|EUR|€|MAD|USD|\$)\s*([0-9]{3,6}[,\.]\d{2})\s*$',  # Amount after currency at end of line
        r'([0-9]{3,6}[,\.]\d{2})\s*$',  # Standalone amounts at end of line
        # General patterns (less specific)
        r'FACTURE\s*.*?([0-9]{3,6}[,\.]\d{2})',           # Find amounts in invoice context
        r'([0-9]{3,6}[,\.]\d{2})\s*(?:EUR|€|DH|MAD|USD|\$)', # Amount before currency
        r'(?:EUR|€|DH|MAD|USD|\$)\s*([0-9]{3,6}[,\.]\d{2})', # Amount after currency
        r'([0-9]{3,6}[,\.]\d{2})',  # Generic monetary amount (3-6 digits)
    ]
    
    for pattern in total_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        metadata["potential_totals"].extend(matches)
    
    # Debug: Print found totals
    if metadata["potential_totals"]:
        print(f"🔍 Found potential totals: {metadata['potential_totals']}")
    else:
        print("⚠️ No totals found in OCR text")
    
    # Look for currency patterns
    currency_patterns = [
        r'(EUR|EURO|€)',  # Euro
        r'(USD|DOLLAR|\$)',  # US Dollar
        r'(DH|MAD|DIRHAM)',  # Moroccan Dirham
        r'(GBP|£)',  # British Pound
        r'DEVISE\s*:?\s*([A-Z]{3})',  # DEVISE : EUR
        r'CURRENCY\s*:?\s*([A-Z]{3})',  # CURRENCY : USD
    ]
    
    metadata["potential_currencies"] = []
    for pattern in currency_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            if isinstance(match, tuple):
                metadata["potential_currencies"].extend(match)
            else:
                metadata["potential_currencies"].append(match)
    
    return metadata

# Debug function to test total detection
def debug_total_detection(text):
    """Debug function to test total detection patterns"""
    print("🔍 DEBUGGING TOTAL DETECTION")
    print("=" * 50)
    
    # Test different total patterns individually
    patterns_to_test = [
        (r'TOTAL\s*[:\s]+([0-9]{1,6}[,\.][0-9]{2})', "TOTAL with colon/space + amount"),
        (r'Total\s*[:\s]+([0-9]{1,6}[,\.][0-9]{2})', "Total with colon/space + amount"),
        (r'MONTANT\s*TOTAL\s*[:\s]*([0-9]{1,6}[,\.][0-9]{2})', "MONTANT TOTAL"),
        (r'NET\s*À\s*PAYER\s*[:\s]*([0-9]{1,6}[,\.][0-9]{2})', "NET À PAYER"),
        (r'([0-9]{3,6}[,\.][0-9]{2})\s*(?:EUR|€|DH|MAD|USD|\$)', "Amount before currency"),
        (r'(?:EUR|€|DH|MAD|USD|\$)\s*([0-9]{3,6}[,\.][0-9]{2})', "Amount after currency"),
        (r'([0-9]{3,6}[,\.][0-9]{2})', "Generic monetary amount")
    ]
    
    all_matches = []
    for pattern, description in patterns_to_test:
        matches = re.findall(pattern, text, re.IGNORECASE)
        print(f"📋 {description}: {matches}")
        all_matches.extend(matches)
    
    print(f"🔍 Total unique amounts found: {list(set(all_matches))}")
    print("=" * 50)
    
    return list(set(all_matches))

# Post-process and validate invoice data
def post_process_invoice_data(data, metadata=None):
    """
    Post-process the parsed invoice data to ensure proper types without automatic calculations
    """
    print("🔍 Post-processing invoice data...")
    
    # Handle null/None values for main invoice fields
    if data.get("M_fe_num") is None:
        data["M_fe_num"] = ""
    if data.get("M_fe_date") is None:
        data["M_fe_date"] = ""
    if data.get("M_fe_devise") is None:
        data["M_fe_devise"] = ""
    
    # Extract currency from metadata if available
    if metadata and metadata.get("potential_currencies"):
        # Normalize currency names
        currency_map = {
            "EUR": "EUR", "EURO": "EUR", "€": "EUR",
            "USD": "USD", "DOLLAR": "USD", "$": "USD",
            "DH": "MAD", "MAD": "MAD", "DIRHAM": "MAD",
            "GBP": "GBP", "£": "GBP"
        }
        
        for currency in metadata["potential_currencies"]:
            normalized_currency = currency_map.get(currency.upper())
            if normalized_currency and not data.get("M_fe_devise"):
                data["M_fe_devise"] = normalized_currency
                print(f"✅ Extracted currency from metadata: {normalized_currency}")
                break
    
    # Default to MAD if no currency found
    if not data.get("M_fe_devise"):
        data["M_fe_devise"] = "MAD"
    
    # Ensure numeric fields have proper defaults
    if data.get("M_fe_Pnet") is None:
        data["M_fe_Pnet"] = 0.0
    if data.get("M_fe_Pbrute") is None:
        data["M_fe_Pbrute"] = 0.0  
    if data.get("M_fe_valDev") is None:
        data["M_fe_valDev"] = 0.0
    
    # Convert main totals to proper numeric types (NO automatic conversion)
    try:
        # Handle M_fe_Pnet - extract weight values properly
        if isinstance(data.get("M_fe_Pnet"), str):
            pnet_str = data["M_fe_Pnet"].replace(",", ".").replace("KGS", "").replace("KG", "").strip()
            # Extract number from string
            numbers = re.findall(r'[\d.]+', pnet_str)
            if numbers:
                data["M_fe_Pnet"] = float(numbers[0])
            else:
                data["M_fe_Pnet"] = 0.0
        else:
            data["M_fe_Pnet"] = float(data.get("M_fe_Pnet", 0))
            
        # Handle M_fe_Pbrute - extract weight values properly  
        if isinstance(data.get("M_fe_Pbrute"), str):
            pbrute_str = data["M_fe_Pbrute"].replace(",", ".").replace("KGS", "").replace("KG", "").strip()
            # Extract number from string
            numbers = re.findall(r'[\d.]+', pbrute_str)
            if numbers:
                data["M_fe_Pbrute"] = float(numbers[0])
            else:
                data["M_fe_Pbrute"] = 0.0
        else:
            data["M_fe_Pbrute"] = float(data.get("M_fe_Pbrute", 0))
        
        # Handle M_fe_valDev specially for monetary values (EXTRACT from metadata, don't calculate)
        if isinstance(data.get("M_fe_valDev"), str):
            val_str = data["M_fe_valDev"].replace(",", ".").replace(" ", "")
            
            # Check if it's a written amount (like "DEUX CENT SOIXANTE DEUX EUR 50 CTS")
            if any(word in val_str.upper() for word in ["DEUX", "TROIS", "QUATRE", "CINQ", "CENT", "EUR", "CTS"]):
                # Try to extract from the OCR text - look for TOTAL patterns in metadata
                print(f"🔍 Found written amount: {data['M_fe_valDev']}")
                # Use metadata totals instead of trying to parse written amounts
                if metadata and metadata.get("potential_totals"):
                    # Look for the most reasonable total value (prioritize larger amounts)
                    best_total = 0.0
                    for total in metadata["potential_totals"]:
                        try:
                            total_clean = total.replace(",", ".")
                            total_val = float(total_clean)
                            # Prioritize values in reasonable invoice range (50-50000)
                            if 50 <= total_val <= 50000 and total_val > best_total:
                                best_total = total_val
                        except:
                            continue
                    
                    if best_total > 0:
                        data["M_fe_valDev"] = best_total
                        print(f"✅ Found numeric total from metadata: {best_total}")
                    else:
                        data["M_fe_valDev"] = 0.0
                        print("⚠️ No reasonable total found in metadata")
                else:
                    data["M_fe_valDev"] = 0.0
                    print("⚠️ No metadata available for total extraction")
            else:
                # Extract number from string (handle currency symbols)
                numbers = re.findall(r'[\d.]+', val_str)
                if numbers:
                    data["M_fe_valDev"] = float(numbers[0])
                else:
                    data["M_fe_valDev"] = 0.0
        else:
            # If M_fe_valDev is already numeric, use it as-is
            if data.get("M_fe_valDev") is None or data.get("M_fe_valDev") == 0:
                # Try to get total from metadata if main field is empty/zero
                if metadata and metadata.get("potential_totals"):
                    best_total = 0.0
                    for total in metadata["potential_totals"]:
                        try:
                            total_clean = total.replace(",", ".")
                            total_val = float(total_clean)
                            # Prioritize values in reasonable invoice range
                            if 50 <= total_val <= 50000 and total_val > best_total:
                                best_total = total_val
                        except:
                            continue
                    
                    if best_total > 0:
                        data["M_fe_valDev"] = best_total
                        print(f"✅ Extracted total from metadata: {best_total}")
                    else:
                        data["M_fe_valDev"] = 0.0
                else:
                    data["M_fe_valDev"] = float(data.get("M_fe_valDev", 0))
    except (ValueError, TypeError):
        data["M_fe_Pnet"] = 0.0
        data["M_fe_Pbrute"] = 0.0
        data["M_fe_valDev"] = 0.0
    
    # Ensure items exist
    if "items" not in data or not isinstance(data["items"], list):
        data["items"] = []
    
    # Process each item without any calculations
    for item in data["items"]:
        # Ensure all item fields exist with proper defaults
        item.setdefault("AvecSansPaiment", "")
        item.setdefault("M_fl_Ngp", "")
        item.setdefault("M_fl_art", "")
        item.setdefault("M_fl_desig", "")
        item.setdefault("M_fl_orig", "MAROC")  # Default to Morocco if not found
        item.setdefault("quantity", 1)
        item.setdefault("M_fl_unite", "PCS")
        item.setdefault("M_fl_PNet", 0)  # Default to 0 instead of "À CALCULER"
        item.setdefault("M_fl_PBrut", 0.0)
        item.setdefault("M_fl_valDev", 0.0)
        
        # Handle None values
        for key in item:
            if item[key] is None:
                if key in ["M_fl_PBrut", "M_fl_valDev"]:
                    item[key] = 0.0
                elif key in ["M_fl_PNet"]:
                    item[key] = 0  # Set to 0 instead of placeholder text
                elif key == "M_fl_orig":
                    item[key] = "MAROC"  # Default origin to Morocco
                else:
                    item[key] = ""
    
    # Auto-assign NGP codes using AI if they're missing
    print("🤖 Starting enhanced AI-powered NGP code assignment...")
    product_descriptions = []
    items_needing_ngp = []
    
    for i, item in enumerate(data["items"]):
        # Check if NGP code is missing or placeholder
        current_ngp = item.get("M_fl_Ngp", "").strip()
        if not current_ngp or current_ngp == "" or current_ngp == "CODE REQUIS":
            if item.get("M_fl_desig") and item.get("M_fl_desig").strip():
                product_descriptions.append(item["M_fl_desig"])
                items_needing_ngp.append(i)
                print(f"🔍 Product needing NGP: '{item['M_fl_desig']}'")
    
    if product_descriptions:
        print(f"🔍 Finding NGP codes for {len(product_descriptions)} products using AI...")
        ai_classifications = find_ngp_codes_with_ai(product_descriptions)
        
        # Apply AI-found NGP codes to items with enhanced validation
        for i, classification in enumerate(ai_classifications):
            if i < len(items_needing_ngp):
                item_index = items_needing_ngp[i]
                ngp_code = classification.get("ngp_code", "")
                confidence = classification.get("confidence", "unknown")
                match_type = classification.get("match_type", "unknown")
                reasoning = classification.get("reasoning", "")
                
                if ngp_code and len(ngp_code) >= 6:  # Validate NGP code format
                    data["items"][item_index]["M_fl_Ngp"] = ngp_code
                    print(f"✅ Assigned NGP {ngp_code} to '{classification.get('description', '')}' ({confidence} confidence, {match_type} match)")
                    if reasoning:
                        print(f"   📝 Reasoning: {reasoning}")
                else:
                    print(f"⚠️ Invalid/missing NGP code for '{classification.get('description', '')}'")
                    data["items"][item_index]["M_fl_Ngp"] = ""  # Keep empty for manual entry
    else:
        print("ℹ️ All products already have NGP codes assigned.")
    
    print("🤖 AI NGP assignment completed.")
    
    # Final NGP validation - ensure no null/N/A values remain
    print("🔍 Final NGP validation...")
    for item_idx, item in enumerate(data["items"]):
        current_ngp = item.get("M_fl_Ngp", "").strip()
        if not current_ngp or current_ngp.upper() in ['N/A', 'NULL', 'NONE', '']:
            # Assign default furniture code instead of leaving empty
            item["M_fl_Ngp"] = "94039000"  # Generic "other wooden furniture"
            print(f"⚠️ Assigned default NGP 94039000 to item {item_idx + 1}: {item.get('M_fl_desig', 'Unknown')}")
    
    # Enhanced data validation and processing
    print("🔍 Starting enhanced data validation...")
    
    # Validate and clean invoice-level data
    if data.get("M_fe_num"):
        # Clean invoice number (remove special characters but keep alphanumeric)
        data["M_fe_num"] = re.sub(r'[^\w\-/]', '', str(data["M_fe_num"]))
    
    if data.get("M_fe_date"):
        # Validate and standardize date format
        date_str = str(data["M_fe_date"])
        if not re.match(r'\d{4}-\d{2}-\d{2}', date_str):
            print(f"⚠️ Date format issue: {date_str}")
    
    # Process each item with enhanced validation
    for item_idx, item in enumerate(data["items"]):
        print(f"🔍 Validating item {item_idx + 1}: {item.get('M_fl_desig', 'Unknown')}")
        
        # Ensure required fields have proper values
        if not item.get("M_fl_desig"):
            item["M_fl_desig"] = f"Article {item_idx + 1}"
            print(f"   ⚠️ Added default designation")
            
        # Convert numeric fields to proper types with enhanced validation
        try:
            # Handle M_fl_valDev - extract monetary values properly
            if isinstance(item["M_fl_valDev"], str):
                try:
                    # Clean and convert monetary values
                    val_str = item["M_fl_valDev"].replace(",", ".").replace(" ", "").replace("€", "").replace("EUR", "")
                    # Extract number from string (handle currency symbols)
                    numbers = re.findall(r'[\d.]+', val_str)
                    if numbers:
                        item["M_fl_valDev"] = float(numbers[0])
                    else:
                        item["M_fl_valDev"] = 0.0
                except Exception as e:
                    print(f"   ⚠️ Value conversion error: {e}")
                    item["M_fl_valDev"] = 0.0
            else:
                item["M_fl_valDev"] = float(item.get("M_fl_valDev", 0)) if item.get("M_fl_valDev") else 0.0

            # If item value is 0 and we have an invoice total with only one item, use the total
            if item["M_fl_valDev"] == 0.0 and data.get("M_fe_valDev", 0) > 0:
                # Count total items to see if we can distribute the total
                total_items = len(data.get("items", []))
                if total_items == 1:
                    # Single item gets the full total
                    item["M_fl_valDev"] = data["M_fe_valDev"]
                    print(f"   ✅ Assigned total invoice value to single item: {item['M_fl_valDev']}")
                elif total_items > 1:
                    # Multiple items, distribute equally if no other values
                    all_items_zero = all(it.get("M_fl_valDev", 0) == 0 for it in data["items"])
                    if all_items_zero:
                        item["M_fl_valDev"] = data["M_fe_valDev"] / total_items
                        print(f"   ✅ Distributed total value equally: {item['M_fl_valDev']}")

            # Handle weights with validation
                    print(f"✅ Assigned total invoice value {data['M_fe_valDev']} to single item")

            item["M_fl_PBrut"] = float(item.get("M_fl_PBrut", 0))
            item["quantity"] = int(item.get("quantity", 1)) if item.get("quantity") else 1
            
            # Handle M_fl_PNet - extract as provided, no calculations
            if isinstance(item["M_fl_PNet"], str):
                try:
                    # Try to extract number from string
                    pnet_str = item["M_fl_PNet"].replace(",", ".")
                    if pnet_str and any(c.isdigit() for c in pnet_str):
                        item["M_fl_PNet"] = float(re.findall(r'[\d.]+', pnet_str)[0])
                    else:
                        item["M_fl_PNet"] = 0
                except:
                    item["M_fl_PNet"] = 0
            else:
                item["M_fl_PNet"] = float(item.get("M_fl_PNet", 0)) if item.get("M_fl_PNet") else 0
                
        except (ValueError, TypeError):
            item["M_fl_PBrut"] = 0.0
            item["M_fl_valDev"] = 0.0
            item["M_fl_PNet"] = 0
            item["quantity"] = 1
    
    print(f"📊 Invoice totals (extracted) - Pnet: {data['M_fe_Pnet']}, Pbrute: {data['M_fe_Pbrute']}, ValDev: {data['M_fe_valDev']}")
    print(f"📋 Processed {len(data['items'])} items without calculations")
    
    return data

# Local Llama API Extractor
def parse_invoice_with_llama(text, metadata=None):
    # Get Llama API URL from environment variable
    llama_api_url = os.environ.get("LLAMA_API_URL", "http://38.46.220.18:5000/api/ask")
    
    headers = {
        "Content-Type": "application/json"
    }
    
    # Pre-process text to highlight totals for Llama
    def highlight_totals_in_text(text):
        """Highlight potential totals in the text to make them more visible to Llama"""
        highlighted_text = text
        
        # Patterns to highlight for totals (enhanced for your invoice format)
        total_highlight_patterns = [
            # High priority patterns from your example
            r'(Montant\s*TTC\s*[:\s]*\d+[,\.]\d{2})',      # Montant TTC 180.894,20
            r'(TOTAL\s*TTC\s*[:\s]*\d+[,\.]\d{2})',        # TOTAL TTC 180.894,20
            r'(Montant\s*HT\s*[:\s]*\d+[,\.]\d{2})',       # Montant HT 180.894,20
            r'(TOTAL\s*HT\s*[:\s]*\d+[,\.]\d{2})',         # TOTAL HT 180.894,20
            r'(Valeur\s*Totale\s*[:\s]*\d+[,\.]\d{2})',    # Valeur Totale
            r'(Valeur\s*devise\s*[:\s]*\d+[,\.]\d{2})',    # Valeur devise
            # Standard patterns
            r'(TOTAL\s*[:\s]*\d+[,\.]\d{2})',
            r'(Total\s*[:\s]*\d+[,\.]\d{2})',  
            r'(MONTANT\s*TOTAL\s*[:\s]*\d+[,\.]\d{2})',
            r'(Montant\s*Total\s*[:\s]*\d+[,\.]\d{2})',
            r'(NET\s*À\s*PAYER\s*[:\s]*\d+[,\.]\d{2})',
            r'(À\s*PAYER\s*[:\s]*\d+[,\.]\d{2})',
            r'(SOUS\s*TOTAL\s*[:\s]*\d+[,\.]\d{2})',
            r'(Prix\s*total\s*[:\s]*\d+[,\.]\d{2})',
            r'(Valeur\s*totale\s*[:\s]*\d+[,\.]\d{2})',
            # Currency patterns
            r'(\d+[,\.]\d{2}\s*(?:EUR|€|DH|MAD|USD|\$))',
            r'((?:EUR|€|DH|MAD|USD|\$)\s*\d+[,\.]\d{2})',
            # Large amounts (like 180.894,20)
            r'(\d{3,6}[,\.]\d{3}[,\.]\d{2})',  # Pattern like 180.894,20
            r'(\d{3,6}[,\.]\d{2})',  # Standard amounts like 3208,50
        ]
        
        # Highlight each pattern with >>> markers
        for pattern in total_highlight_patterns:
            highlighted_text = re.sub(pattern, r'>>> \1 <<<', highlighted_text, flags=re.IGNORECASE)
        
        return highlighted_text
    
    # Highlight totals in the text
    highlighted_text = highlight_totals_in_text(text)
    total_count = len(re.findall(r'>>>', highlighted_text))
    print(f"🔍 Highlighted {total_count} potential totals in text")
    
    # Extract and show the highlighted totals for debugging
    if total_count > 0:
        highlighted_parts = re.findall(r'>>>\s*(.+?)\s*<<<', highlighted_text)
        print("🎯 Found these potential totals:")
        for i, part in enumerate(highlighted_parts[:3]):  # Show first 3
            print(f"   {i+1}. {part.strip()}")
    else:
        print("⚠️ No totals highlighted in text - Llama will need to find them manually")
    
    # Build metadata hints for better extraction (limit to ensure consistency)
    hints = ""
    if metadata:
        if metadata.get("potential_invoice_numbers"):
            # Take only the first invoice number for consistency
            hints += f"\nInvoice number found: {metadata['potential_invoice_numbers'][0]}"
        if metadata.get("potential_dates"):
            # Take only the first date for consistency
            hints += f"\nDate found: {metadata['potential_dates'][0]}"
        if metadata.get("potential_weights"):
            # Take only first few weights for consistency
            hints += f"\nWeights found: {', '.join(metadata['potential_weights'][:2])}"
        if metadata.get("potential_totals"):
            # Take only first few totals for consistency
            hints += f"\nTotals found: {', '.join(metadata['potential_totals'][:2])}"
        if metadata.get("potential_currencies"):
            # Take only first currency for consistency
            hints += f"\nCurrency found: {metadata['potential_currencies'][0]}"
    
    prompt = f"""Analysez minutieusement cette facture française et extrayez les données avec PRÉCISION MAXIMALE.

🎯 PRIORITÉ ABSOLUE: EXTRACTION LIGNE PAR LIGNE
Le texte ci-dessous a été structuré avec chaque élément sur sa propre ligne pour faciliter l'extraction.

RÈGLES D'EXTRACTION CRITIQUES:
1. Numéro de facture: Cherchez "FACTURE N°", "N°", "FA" suivi du numéro exact (ex: FA009421)
2. Date: Format DD/MM/YYYY ou DD-MM-YYYY → convertir en YYYY-MM-DD

3. 🔍 EXTRACTION DES TOTAUX - LISEZ LIGNE PAR LIGNE:
   ✅ Cherchez "Montant TTC 180.894,20" → extraire 180894.20
   ✅ Cherchez "TOTAL TTC 180.894,20" → extraire 180894.20  
   ✅ Cherchez "Montant HT 180.894,20" → extraire 180894.20
   ✅ Cherchez "180.894,20" seul sur une ligne → extraire 180894.20
   ✅ Cherchez "TOTAL : 262.50" → extraire 262.50
   ✅ Cherchez "NET À PAYER : 3842.75" → extraire 3842.75
   
   ❌ IGNOREZ complètement les montants écrits en toutes lettres
   ⚠️ Convertissez virgules en points (255,50 → 255.50)
   ⚠️ Retirez points des milliers (180.894,20 → 180894.20)

4. 📋 EXTRACTION DES ARTICLES - CHAQUE LIGNE CONTIENT:
   - Code article (si présent)
   - Description du produit
   - Quantité
   - Unité (Pièce, Mètre, etc.)
   - Prix unitaire
   - Montant total de la ligne
   
   Exemple d'extraction:
   Ligne: "STRUCTURE- STRUCTURE MURAL EN BOIS 516 cm L/295 cm H 1,00 Pièce 3 208,50 3.208,50"
   → Extraire: description="STRUCTURE MURAL EN BOIS 516 cm L/295 cm H", quantity=1, unite="Pièce", valeur=3208.50

5. 🏷️ CODES NGP: Laissez vides, ils seront assignés automatiquement
6. 🌍 ORIGINE: Cherchez "ORIGINE", "MADE IN" - si absent, laissez vide
7. 💰 DEVISE: Cherchez "EUR", "DH", "MAD", "€", "$"

🚨 INSTRUCTIONS SPÉCIALES POUR LE FORMAT LIGNE PAR LIGNE:
- LISEZ CHAQUE LIGNE SÉPARÉMENT
- Une ligne peut contenir: "Description + Quantité + Unité + Prix + Montant"
- Les totaux sont souvent sur des lignes séparées
- Les dates sont sur des lignes séparées
- Les numéros de facture sont sur des lignes séparées
- Utilisez le contexte des lignes adjacentes pour comprendre la structure

{hints}

RETOURNEZ ce JSON EXACT (montants extraits directement du texte):
{{
  "M_fe_num": "numéro_facture_exact",
  "M_fe_date": "YYYY-MM-DD",
  "M_fe_devise": "code_devise_trouvé_ou_vide",
  "items": [
    {{
      "AvecSansPaiment": "",
      "M_fl_Ngp": "",
      "M_fl_art": "code_article_si_disponible",
      "M_fl_desig": "description_produit_complète",
      "M_fl_orig": "pays_origine_si_mentionné_sinon_vide",
      "quantity": nombre_quantité_réelle,
      "M_fl_unite": "PCS",
      "M_fl_PNet": valeur_poids_net_numérique_ou_0,
      "M_fl_PBrut": valeur_poids_brut_numérique,
      "M_fl_valDev": valeur_ligne_numérique_extraite_du_texte
    }}
  ],
  "M_fe_Pnet": total_poids_net_numérique,
  "M_fe_Pbrute": total_poids_brut_numérique,
  "M_fe_valDev": montant_total_EXTRAIT_EXACTEMENT_du_texte_OCR_ci_dessous
}}

EXEMPLES D'EXTRACTION DE TOTAUX (basés sur votre format d'facture):
- Si le texte contient "Montant TTC 180.894,20" → M_fe_valDev: 180894.20
- Si le texte contient "TOTAL TTC 25.550,50" → M_fe_valDev: 25550.50
- Si le texte contient "Montant HT 180.894,20" → M_fe_valDev: 180894.20
- Si le texte contient "TOTAL : 262.50" → M_fe_valDev: 262.50
- Si le texte contient "NET À PAYER : 3842.75" → M_fe_valDev: 3842.75
- Si le texte contient "À PAYER 845,20 DH" → M_fe_valDev: 845.20
- Si le texte contient "Valeur Totale 1234.50" → M_fe_valDev: 1234.50
- Si aucun total trouvé → M_fe_valDev: 0.0

TEXTE DE LA FACTURE STRUCTURÉ LIGNE PAR LIGNE (totaux marqués avec >>> <<<):
{highlighted_text}"""

    # Prepare the request data for local Llama API
    data = {
        "question": prompt,
        "max_tokens": 4000,
        "temperature": 0.1,
        "top_p": 0.9
    }

    try:
        print("🚀 Making request to local Llama API...")
        print(f"📝 Prompt length: {len(prompt)} characters")
        
        response = requests.post(
            llama_api_url, 
            headers=headers, 
            json=data,
            timeout=120  # Increased timeout for local API
        )
        
        print(f"🌐 Response status code: {response.status_code}")
        print(f"📥 Response headers: {dict(response.headers)}")
        
        if response.status_code != 200:
            print("❌ llamaAPI error:", response.status_code)
            print("❌ Response text:", response.text)
            print("❌ Request headers:", headers)
            print("❌ Request data:", json.dumps(data, indent=2))
            raise Exception(f"llamaAPI returned {response.status_code}: {response.text}")

        response_json = response.json()
        print("✅ llamaAPI response received successfully")
        return response_json
        
    except requests.exceptions.Timeout:
        print("❌ Llama API request timed out")
        raise Exception("Llama API request timed out after 120 seconds")
    except requests.exceptions.ConnectionError:
        print("❌ Connection error to Llama API")
        raise Exception("Failed to connect to Llama API")
    except requests.exceptions.RequestException as e:
        print(f"❌ Request error: {e}")
        raise Exception(f"Request error: {str(e)}")
    except Exception as e:
        print(f"❌ Unexpected error in Llama request: {e}")
        raise Exception(f"Unexpected error in Llama request: {str(e)}")

# Simple test endpoint
@app.get("/test/")
async def simple_test():
    return {"status": "working", "message": "API is running"}

# Test total detection endpoint
@app.post("/test-totals/")
async def test_total_detection_endpoint(request: Request):
    """Test endpoint to debug total detection with sample text"""
    try:
        data = await request.json()
        sample_text = data.get("text", "")
        
        if not sample_text:
            return {"error": "No text provided"}
        
        # Test total detection
        detected_totals = debug_total_detection(sample_text)
        
        # Also test metadata extraction
        metadata = extract_invoice_metadata(sample_text)
        
        return {
            "detected_totals": detected_totals,
            "metadata": metadata
        }
        
    except Exception as e:
        print(f"❌ Test totals API error: {e}")
        return {"error": str(e)}

# Test database connection and table structure
@app.get("/test-database/")
async def test_database():
    try:
        conn = mysql.connector.connect(
            host='mysql-4791ff0-mohamed-cfcb.c.aivencloud.com',
            port=28974,
            user='avnadmin',
            password='AVNS_awY4JgPDS6TiUUadqdu',
            database='wdoptitransit_khaladi',
            connection_timeout=10
        )
        cursor = conn.cursor()
        
        # Check tables
        cursor.execute("SHOW TABLES")
        tables = [table[0] for table in cursor.fetchall()]
        
        result = {
            "connection": "✅ Connected successfully",
            "database": "wdoptitransit_khaladi",
            "tables": tables,
            "m_dossier_exists": "m_dossier" in tables
        }
        
        # If m_dossier exists, check its structure
        if "m_dossier" in tables:
            cursor.execute("DESCRIBE m_dossier")
            columns = [{"Field": col[0], "Type": col[1]} for col in cursor.fetchall()]
            result["m_dossier_columns"] = columns
            
            # Check if M_Ds_Num column exists
            column_names = [col["Field"] for col in columns]
            result["M_Ds_Num_exists"] = "M_Ds_Num" in column_names
            
            # Count records
            cursor.execute("SELECT COUNT(*) FROM m_dossier")
            count = cursor.fetchone()[0]
            result["m_dossier_count"] = count
            
            # Sample data
            if count > 0:
                cursor.execute("SELECT M_Ds_Num FROM m_dossier LIMIT 5")
                samples = [row[0] for row in cursor.fetchall()]
                result["sample_dossiers"] = samples
        
        cursor.close()
        conn.close()
        return result
        
    except Exception as e:
        return {"error": str(e)}

# Add endpoint to get dossiers
@app.get("/get-dossiers/")
async def get_dossiers_endpoint():
    try:
        print("📡 API: Getting dossiers...")
        dossiers = get_dossiers()
        print(f"📡 API: Returning {len(dossiers)} dossiers")
        return {"dossiers": dossiers}
    except Exception as e:
        print(f"❌ API error: {e}")
        return {"error": str(e), "dossiers": []}

@app.get("/search-ngp/")
async def search_ngp_endpoint(q: str = ""):
    try:
        print(f"📡 API: Searching NGP codes with term: '{q}'")
        ngp_codes = search_ngp_codes(q)
        print(f"📡 API: Returning {len(ngp_codes)} NGP codes")
        return {"ngp_codes": ngp_codes}
    except Exception as e:
        print(f"❌ NGP search API error: {e}")
        return {"error": str(e), "ngp_codes": []}

@app.post("/ai-ngp-lookup/")
async def ai_ngp_lookup_endpoint(request: Request):
    try:
        data = await request.json()
        descriptions = data.get("descriptions", [])
        
        if not descriptions:
            return {"error": "No descriptions provided", "classifications": []}
        
        print(f"🤖 AI NGP lookup for {len(descriptions)} descriptions")
        classifications = find_ngp_codes_with_ai(descriptions)
        
        return {"classifications": classifications}
    except Exception as e:
        print(f"❌ AI NGP lookup API error: {e}")
        return {"error": str(e), "classifications": []}

# Get dossier details from database
def get_dossier_details(dossier_num):
    """Get complete dossier information from m_dossier table"""
    try:
        print(f"🔍 Fetching dossier details for: {dossier_num}")
        connection = mysql.connector.connect(
            host='mysql-4791ff0-mohamed-cfcb.c.aivencloud.com',
            port=28974,
            user='avnadmin',
            password='AVNS_awY4JgPDS6TiUUadqdu',
            database='wdoptitransit_khaladi',
            connection_timeout=10
        )
        
        cursor = connection.cursor(dictionary=True)
        
        # Fetch dossier details
        query = """
        SELECT 
            M_Ds_Num, M_Ds_date, M_Ds_ndum, M_Ds_devise, M_Ds_cours,
            M_Ds_MteR, M_Ds_Darriv, M_Ds_Ddeb, M_Ds_Mtfret, M_Ds_navire,
            M_Ds_cnt, M_Ds_Pnet, M_Ds_Pbrut, M_Ds_Ncolis, M_Ds_Nature,
            M_Ds_Orig, M_Ds_prov, M_Ds_Inco, M_Ds_CodeClient, M_Ds_TypeOp,
            M_Ds_CodeClientFactur, M_Ds_Val_Devise_Total, M_Ds_Statut,
            M_Ds_Etat, M_Ds_NumManifeste, M_Ds_Declarerant, M_Ds_Designation,
            M_Ds_Conteneur, M_DS_MntAco, M_DS_Bureau, M_DS_Regime, M_DS_ShortDum
        FROM m_dossier 
        WHERE M_Ds_Num = %s
        """
        
        cursor.execute(query, (dossier_num,))
        dossier_data = cursor.fetchone()
        
        cursor.close()
        connection.close()
        
        if dossier_data:
            print(f"✅ Dossier details fetched successfully for: {dossier_num}")
            print(f"📊 Found data fields: {list(dossier_data.keys())}")
        else:
            print(f"⚠️ No dossier found for: {dossier_num}")
        
        return dossier_data
    
    except Exception as e:
        print(f"❌ Error fetching dossier details for {dossier_num}: {e}")
        return None

# Get NGP codes from database for search
def search_ngp_codes(search_term="", limit=50):
    """Search NGP codes in the database"""
    try:
        connection = mysql.connector.connect(
            host='mysql-4791ff0-mohamed-cfcb.c.aivencloud.com',
            port=28974,
            user='avnadmin',
            password='AVNS_awY4JgPDS6TiUUadqdu',
            database='wdoptitransit_khaladi',
            connection_timeout=10
        )
        
        cursor = connection.cursor(dictionary=True)
        
        # Search in NGP table (adjust table name as needed)
        if search_term:
            query = """
            SELECT DISTINCT code_ngp, designation 
            FROM m_ngp 
            WHERE code_ngp LIKE %s OR designation LIKE %s 
            ORDER BY code_ngp 
            LIMIT %s
            """
            search_pattern = f"%{search_term}%"
            cursor.execute(query, (search_pattern, search_pattern, limit))
        else:
            query = """
            SELECT DISTINCT code_ngp, designation 
            FROM m_ngp 
            ORDER BY code_ngp 
            LIMIT %s
            """
            cursor.execute(query, (limit,))
        
        ngp_codes = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        print(f"📋 Found {len(ngp_codes)} NGP codes for search term: '{search_term}'")
        return ngp_codes
    
    except Exception as e:
        print(f"❌ Error searching NGP codes: {e}")
        # Return some default NGP codes if database fails
        return [
            {"code_ngp": "84159000", "designation": "Machines et appareils"},
            {"code_ngp": "84799000", "designation": "Autres machines"},
            {"code_ngp": "85437000", "designation": "Machines électriques"}
        ]

# Get available NGP codes from database for AI reference
def get_available_ngp_codes_for_ai():
    """Get available NGP codes from database for AI classification reference"""
    try:
        connection = mysql.connector.connect(
            host='mysql-4791ff0-mohamed-cfcb.c.aivencloud.com',
            port=28974,
            user='avnadmin',
            password='AVNS_awY4JgPDS6TiUUadqdu',
            database='wdoptitransit_khaladi',
            connection_timeout=10
        )
        cursor = connection.cursor(dictionary=True)
        
        # Get all NGP codes with their designations
        query = "SELECT code_ngp, designation FROM m_ngp ORDER BY code_ngp LIMIT 100"
        cursor.execute(query)
        results = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        return results
        
    except Exception as e:
        print(f"❌ Error fetching NGP codes for AI: {e}")
        return []

# Enhanced NGP lookup with Llama API fallback
def find_ngp_with_internet_fallback(product_description):
    """Find NGP codes using Llama API when database doesn't have matches"""
    try:
        # Get Llama API URL from environment variable
        llama_api_url = os.environ.get("LLAMA_API_URL", "http://38.46.220.18:5000/api/ask")
        
        # Create a comprehensive prompt that includes NGP knowledge
        prompt = f"""Tu es un expert en classification NGP (Nomenclature Générale des Produits) pour les douanes marocaines.

PRODUIT À CLASSIFIER: "{product_description}"

Utilisez votre connaissance complète des codes NGP internationaux et marocains pour trouver le code le plus approprié.

CODES NGP FRÉQUENTS POUR RÉFÉRENCE:
MEUBLES EN BOIS (940xxxxx):
- 94036000: Meubles en bois pour chambres à coucher
- 94035000: Meubles en bois pour chambres
- 94039000: Autres meubles en bois 
- 94034000: Meubles de cuisine en bois
- 94038100: Meubles en bois pour bureau
- 94038900: Autres meubles en bois
- 94033000: Meubles en bois pour bureau
- 94037000: Meubles en plastique

BOIS ET OUVRAGES EN BOIS (44xxxxxx):
- 44219000: Autres ouvrages en bois
- 44181000: Fenêtres, portes-fenêtres et leurs cadres
- 44189000: Autres ouvrages de menuiserie
- 44211000: Cintres pour vêtements

STRUCTURES ET PANNEAUX:
- 94036000: Structures de meubles en bois
- 44219000: Panneaux en bois
- 94039000: Supports TV en bois
- 85287100: Supports pour équipements électroniques

INSTRUCTIONS:
1. Analysez le produit et sa catégorie
2. Trouvez le code NGP le PLUS PRÉCIS possible
3. Si incertain, choisissez le code de la catégorie parente
4. TOUJOURS retourner un code valide (jamais null/N/A)

Répondez UNIQUEMENT avec ce JSON:
{{
  "ngp_code": "code_exact_8_chiffres",
  "confidence": "high|medium|low",
  "category": "catégorie_du_produit",
  "reasoning": "explication_du_choix"
}}"""

        headers = {
            "Content-Type": "application/json"
        }
        
        data = {
            "question": prompt,
            "max_tokens": 1024,
            "temperature": 0.1,
            "top_p": 0.8
        }
        
        response = requests.post(
            llama_api_url,
            headers=headers,
            json=data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            assistant_reply = result.get('response', '') or result.get('answer', '') or str(result)
            
            # Extract JSON from response
            import re
            import json
            match = re.search(r'```(?:json)?\s*([\s\S]+?)\s*```', assistant_reply)
            json_string = match.group(1) if match else assistant_reply.strip()
            
            try:
                ngp_data = json.loads(json_string)
                return ngp_data
            except json.JSONDecodeError:
                print(f"❌ Failed to parse NGP response: {json_string[:200]}...")
                return None
        else:
            print(f"❌ Llama NGP lookup failed: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"❌ Error in Llama NGP lookup: {e}")
        return None

def find_ngp_codes_with_ai(product_descriptions):
    """Use Llama AI to find appropriate NGP codes for product descriptions"""
    try:
        # Get Llama API URL from environment variable
        llama_api_url = os.environ.get("LLAMA_API_URL", "http://38.46.220.18:5000/api/ask")
        
        # Get available NGP codes from database for better matching
        available_ngp_codes = get_available_ngp_codes_for_ai()
        
        # Create enhanced context with actual database codes
        if available_ngp_codes:
            ngp_context = "\n".join([f"- {ngp['code_ngp']}: {ngp['designation']}" for ngp in available_ngp_codes])
        else:
            # Fallback with comprehensive furniture codes
            ngp_context = """- 94036000: Meubles en bois pour chambres à coucher
- 94035000: Meubles en bois pour chambres  
- 94039000: Autres meubles en bois
- 44219000: Autres ouvrages en bois
- 94034000: Meubles de cuisine en bois
- 94038100: Meubles en bois pour bureau
- 94038900: Autres meubles en bois
- 94033000: Meubles en bois pour bureau
- 94037000: Meubles en plastique
- 44181000: Fenêtres, portes-fenêtres et leurs cadres
- 44189000: Autres ouvrages de menuiserie
- 85287100: Supports pour équipements électroniques"""
        
        prompt = f"""Tu es un expert en classification NGP (Nomenclature Générale des Produits) pour les douanes marocaines.

CODES NGP DISPONIBLES DANS LA BASE DE DONNÉES:
{ngp_context}

DESCRIPTIONS DE PRODUITS À CLASSIFIER:
{chr(10).join([f"{i+1}. {desc}" for i, desc in enumerate(product_descriptions)])}

RÈGLES DE CLASSIFICATION STRICTES:
1. Utilisez PRIORITAIREMENT les codes NGP listés ci-dessus
2. Si aucun code exact n'existe, utilisez votre connaissance complète des codes NGP internationaux
3. JAMAIS de valeurs null, N/A, ou vides - TOUJOURS retourner un code valide
4. Pour les meubles en bois, privilégiez les codes 940xxxxx
5. Pour les structures/panneaux en bois: 94036000, 94035000, ou 94039000
6. Pour les panneaux TV/supports: 94039000 ou codes meubles appropriés
7. Si incertain, utilisez le code de la catégorie parente (ex: 94039000 pour meubles divers)

PRIORITÉ ABSOLUE: 
- Retournez TOUJOURS un code NGP valide à 8 chiffres
- Utilisez des codes réels et existants uniquement
- Préférez un code proche correct qu'aucun code

FORMAT DE RÉPONSE (JSON UNIQUEMENT):
{{
  "classifications": [
    {{
      "description": "description exacte du produit",
      "ngp_code": "code_8_chiffres_obligatoire",
      "confidence": "high|medium|low",
      "reasoning": "pourquoi ce code a été choisi",
      "match_type": "database|internet|category",
      "source": "base_de_données|connaissance_internationale"
    }}
  ]
}}"""

        headers = {
            "Content-Type": "application/json"
        }
        
        data = {
            "question": prompt,
            "max_tokens": 2000,
            "temperature": 0.1,
            "top_p": 0.9
        }
        
        response = requests.post(
            llama_api_url,
            headers=headers,
            json=data,
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            assistant_reply = result.get('response', '') or result.get('answer', '') or str(result)
            
            # Extract JSON from response
            import re
            import json
            match = re.search(r'```(?:json)?\s*([\s\S]+?)\s*```', assistant_reply)
            json_string = match.group(1) if match else assistant_reply.strip()
            
            try:
                ai_classifications = json.loads(json_string)
                classifications = ai_classifications.get('classifications', [])
                
                # Validate and enhance classifications - ensure no null/N/A values
                validated_classifications = []
                for i, classification in enumerate(classifications):
                    ngp_code = classification.get('ngp_code', '')
                    
                    # If no valid NGP code, use fallback
                    if not ngp_code or len(ngp_code) < 6 or ngp_code.upper() in ['N/A', 'NULL', 'NONE']:
                        # Assign a generic furniture code
                        classification['ngp_code'] = '94039000'  # Generic "other wooden furniture"
                        classification['confidence'] = 'low'
                        classification['source'] = 'default_fallback'
                        classification['reasoning'] = 'Code générique assigné - classification manuelle recommandée'
                    
                    validated_classifications.append(classification)
                
                print(f"✅ AI found {len(validated_classifications)} NGP classifications (no null values)")
                return validated_classifications
                
            except json.JSONDecodeError:
                print(f"❌ Failed to parse AI response: {json_string[:200]}...")
                
                # Fallback: assign default codes to prevent null values
                fallback_classifications = []
                for desc in product_descriptions:
                    fallback_classifications.append({
                        "description": desc,
                        "ngp_code": "94039000",  # Generic furniture code
                        "confidence": "low",
                        "reasoning": "Code par défaut - classification manuelle recommandée",
                        "source": "fallback_default"
                    })
                return fallback_classifications
        else:
            print(f"❌ AI NGP lookup failed: {response.status_code}")
            
            # Fallback: assign default codes
            fallback_classifications = []
            for desc in product_descriptions:
                fallback_classifications.append({
                    "description": desc,
                    "ngp_code": "94039000",  # Generic furniture code
                    "confidence": "low",
                    "reasoning": "Code par défaut - API indisponible",
                    "source": "api_fallback"
                })
            return fallback_classifications
            
    except Exception as e:
        print(f"❌ Error in AI NGP lookup: {e}")
        
        # Final fallback: ensure we never return empty
        fallback_classifications = []
        for desc in product_descriptions:
            fallback_classifications.append({
                "description": desc,
                "ngp_code": "94039000",  # Generic furniture code
                "confidence": "low",
                "reasoning": "Code par défaut - erreur système",
                "source": "error_fallback"
            })
        return fallback_classifications

# Upload form
@app.get("/", response_class=HTMLResponse)
async def serve_homepage():
    return """
    <html>

<head>
  <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
  <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
</head>

<body class=" bg-[#F9F9F9]">
  <nav class="bg-[#365D98] text-white">
    <div class="max-w-screen-xl flex flex-wrap items-center justify-between mx-auto p-3">
      <a href="/" class="flex items-center space-x-3 rtl:space-x-reverse">
        <span class="self-center text-2xl font-semibold whitespace-nowrap ">OptimumTransit<span
            class="ms-1 text-[10px]">OCR</span></span>
      </a>
      
      <div class="hidden w-full md:block md:w-auto " id="navbar-default">
        <ul
          class="font-medium flex flex-col p-4 md:p-0 mt-4 border border-gray-100 rounded-lg  md:flex-row md:space-x-8 rtl:space-x-reverse md:mt-0 md:border-0 ">
           
                    <li>
                        <a href="/invoices" class="block py-2 px-3 text-white rounded-sm md:bg-transparent  md:p-0 "
                            aria-current="page">Historique des Factures</a>
                    </li>

        </ul>
      </div>
    </div>
  </nav>
  <section class="container mx-auto mt-5 p-10 bg-white shadow-lg rounded-lg ">
    <!-- <h2 class="text-start text-lg text-[#365D98] font-medium">Scanner Les factures</h2> -->
    <!-- <h1 class="mb-1 text-3xl text-center font-bold text-[#365D98]">OptimumTransit OCR</h1>
    <p class="text-center text-gray-500 ">Powered by <a href="https://www.PCHALLE.com/" class="text-red-700" target="_blank" rel="noopener noreferrer">PCHALLE</a></p> -->
    <div class="flex flex-col items-center justify-center my-auto h-[70vh]">
     

      <form action="/upload-invoice/" method="post" enctype="multipart/form-data" id="uploadForm"
        class="text-center flex flex-col items-center justify-center w-96 md:w-1/2 lg:w-1/3">
        
        <!-- Dossier Selection -->
        <div class="w-full mb-6">
          <label for="dossier" class="text-[#365D98] font-semibold text-lg block mb-2">Sélectionner le numéro de dossier *</label>
          <div class="relative">
            <input type="text" id="dossierInput" name="dossier" required autocomplete="off"
              class="w-full p-3 text-gray-700 border border-gray-300 rounded-lg focus:outline-none focus:border-[#365D98] bg-white"
              placeholder="Tapez pour rechercher un dossier..." onkeyup="filterDossiers()" onclick="showDropdown()">
            <div id="dossierDropdown" class="absolute z-10 w-full bg-white border border-gray-300 rounded-lg shadow-lg max-h-60 overflow-y-auto hidden">
              <div id="dossierList">
                <!-- Dossiers will be loaded here -->
              </div>
            </div>
          </div>
          <div id="dossierError" class="text-red-500 text-sm mt-1 hidden">Veuillez sélectionner un numéro de dossier</div>
        </div>

        <label for="pdf" class="text-[#365D98] font-semibold text-lg">Joindre la facture</label>
        <p class="text-gray-500 text-sm mb-8">Format accepté: PDF , Image (JPG, PNG)</p>

        <input type="file" id="pdf"
          class="ml-4  p-1 w-full text-slate-500 text-sm rounded-full leading-6 file:bg-gray-200 file:text-gray-700 file:font-semibold file:border-none file:px-4 file:py-1 file:mr-6 file:rounded-full hover:file:bg-violet-100 border border-gray-300"
          name="pdf" accept="application/pdf, image/png, image/jpeg" required>
        
        <button type="submit" id="submitBtn" class="bg-[#365D98] rounded px-2 py-1 text-white mt-8 w-40 flex items-center justify-center">
          <span id="btnText">Générer</span>
          <div id="spinner" class="hidden ml-2">
            <svg class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
          </div>
        </button>
      </form>
      
      <!-- Loading overlay -->
      <div id="loadingOverlay" class="hidden fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
        <div class="bg-white rounded-lg p-8 flex flex-col items-center">
          <div class="animate-spin rounded-full h-16 w-16 border-b-2 border-[#365D98] mb-4"></div>
          <h3 class="text-lg font-semibold text-[#365D98] mb-2">Traitement en cours...</h3>
          <p class="text-gray-600 text-center">Analyse de la facture avec l'IA<br>Veuillez patienter</p>
        </div>
      </div>

      <script>
        let allDossiers = [];
        let selectedDossier = '';

        // Load dossiers on page load
        async function loadDossiers() {
          try {
            console.log('🔍 Loading dossiers from API...');
            const response = await fetch('/get-dossiers/');
            console.log('📡 Response status:', response.status);
            
            const data = await response.json();
            console.log('📡 Response data:', data);
            
            if (data.dossiers && data.dossiers.length > 0) {
              console.log(`✅ Found ${data.dossiers.length} dossiers`);
              allDossiers = data.dossiers;
              populateDossierList(allDossiers);
            } else {
              console.log('❌ No dossiers found or error occurred');
              
              // Show SweetAlert for no dossiers
              Swal.fire({
                icon: 'info',
                title: 'Aucun dossier trouvé',
                text: 'Aucun numéro de dossier n\\\'est disponible dans la base de données.',
                confirmButtonText: 'Compris',
                confirmButtonColor: '#365D98'
              });
            }
          } catch (error) {
            console.error('Error loading dossiers:', error);
            
            // Show SweetAlert for loading error
            Swal.fire({
              icon: 'error',
              title: 'Erreur de chargement',
              text: 'Impossible de charger les numéros de dossier. Veuillez rafraîchir la page.',
              confirmButtonText: 'Rafraîchir',
              confirmButtonColor: '#365D98'
            }).then((result) => {
              if (result.isConfirmed) {
                window.location.reload();
              }
            });
          }
        }

        function populateDossierList(dossiers) {
          const list = document.getElementById('dossierList');
          list.innerHTML = '';
          
          dossiers.forEach(dossier => {
            const item = document.createElement('div');
            item.className = 'px-4 py-2 hover:bg-blue-50 cursor-pointer border-b border-gray-100';
            item.textContent = dossier;
            item.onclick = () => selectDossier(dossier);
            list.appendChild(item);
          });
        }

        function selectDossier(dossier) {
          selectedDossier = dossier;
          document.getElementById('dossierInput').value = dossier;
          document.getElementById('dossierDropdown').classList.add('hidden');
          document.getElementById('dossierError').classList.add('hidden');
          document.getElementById('dossierInput').classList.remove('border-red-500');
        }

        function filterDossiers() {
          const input = document.getElementById('dossierInput').value.toLowerCase();
          const filtered = allDossiers.filter(dossier => 
            dossier.toLowerCase().includes(input)
          );
          populateDossierList(filtered);
          showDropdown();
        }

        function showDropdown() {
          if (allDossiers.length > 0) {
            document.getElementById('dossierDropdown').classList.remove('hidden');
          }
        }

        // Hide dropdown when clicking outside
        document.addEventListener('click', function(event) {
          const dropdown = document.getElementById('dossierDropdown');
          const input = document.getElementById('dossierInput');
          
          if (!dropdown.contains(event.target) && event.target !== input) {
            dropdown.classList.add('hidden');
          }
        });

        // Load dossiers when page loads
        document.addEventListener('DOMContentLoaded', loadDossiers);

        document.getElementById('uploadForm').addEventListener('submit', function(e) {
          console.log('Form submission started');
          
          // Validate dossier selection
          const dossierInput = document.getElementById('dossierInput');
          const dossierError = document.getElementById('dossierError');
          
          if (!dossierInput.value || !allDossiers.includes(dossierInput.value)) {
            console.log('No valid dossier selected');
            e.preventDefault();
            
            // Show SweetAlert for missing dossier
            Swal.fire({
              icon: 'warning',
              title: 'Numéro de dossier requis',
              text: 'Veuillez sélectionner un numéro de dossier valide avant de continuer.',
              confirmButtonText: 'Compris',
              confirmButtonColor: '#365D98',
              showClass: {
                popup: 'animate__animated animate__fadeInDown'
              },
              hideClass: {
                popup: 'animate__animated animate__fadeOutUp'
              }
            });
            
            dossierError.classList.remove('hidden');
            dossierInput.classList.add('border-red-500');
            return false;
          } else {
            dossierError.classList.add('hidden');
            dossierInput.classList.remove('border-red-500');
          }
          
          // Validate file selection
          const fileInput = document.getElementById('pdf');
          console.log('File input:', fileInput);
          console.log('Files:', fileInput.files);
          
          if (!fileInput.files || fileInput.files.length === 0) {
            console.log('No file selected');
            e.preventDefault();
            
            // Show SweetAlert for missing file
            Swal.fire({
              icon: 'warning',
              title: 'Fichier requis',
              text: 'Veuillez sélectionner un fichier à traiter.',
              confirmButtonText: 'Compris',
              confirmButtonColor: '#365D98'
            });
            return false;
          } else {
            // Validate file type
            const file = fileInput.files[0];
            console.log('Selected file:', file);
            console.log('File name:', file.name);
            console.log('File type:', file.type);
            console.log('File size:', file.size);
            
            // Check file type
            const allowedTypes = ['application/pdf', 'image/png', 'image/jpeg', 'image/jpg'];
            if (!allowedTypes.includes(file.type)) {
              e.preventDefault();
              
              // Show SweetAlert for invalid file type
              Swal.fire({
                icon: 'error',
                title: 'Type de fichier non supporté',
                text: 'Veuillez sélectionner un PDF ou une image (PNG, JPG).',
                confirmButtonText: 'Compris',
                confirmButtonColor: '#365D98'
              });
              return false;
            }
          }
          
          console.log('Submitting form to main endpoint with dossier:', dossierInput.value);
          
          // Show loading elements
          document.getElementById('loadingOverlay').classList.remove('hidden');
          document.getElementById('btnText').textContent = 'Traitement...';
          document.getElementById('spinner').classList.remove('hidden');
          
          // Allow form submission to proceed
          return true;
        });
        
        // Additional validation on file input change
        document.getElementById('pdf').addEventListener('change', function(e) {
          const file = e.target.files[0];
          console.log('File changed:', file);
          
          if (file) {
            console.log('File details - Name:', file.name, 'Type:', file.type, 'Size:', file.size);
          }
        });
      </script>
      <div class="text-center mt-3">
        <!-- <a href="/invoices" class="btn btn-outline-secondary">View All Invoices</a> -->
      </div>
    </div>
  </section>
</body>
<footer class="bg-[#365D98] text-white text-center py-4 mt-5 absolute bottom-0 w-full">
  <p>&copy; 2025 OptimumTransit. Tous droits réservés.</p>
  <p>Développé par <a href="https://www.PCHALLE.com/" class="text-red-700" target="_blank" rel="noopener noreferrer">PCHALLE</a></p>
</footer>
</body>

</html>
    """

# View all invoices
@app.get("/invoices", response_class=HTMLResponse)
async def view_invoices(request: Request):
    try:
        conn = mysql.connector.connect(
            host='mysql-4791ff0-mohamed-cfcb.c.aivencloud.com',
            port=28974,
            user='avnadmin',
            password='AVNS_awY4JgPDS6TiUUadqdu',
            database='wdoptitransit_khaladi',
            connection_timeout=10
        )
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM invoices ORDER BY id DESC")
        invoices = cursor.fetchall()

        for invoice in invoices:
            cursor.execute("SELECT * FROM invoice_items WHERE invoice_id = %s", (invoice["id"],))
            invoice["items"] = cursor.fetchall()

        cursor.close()
        conn.close()

        return templates.TemplateResponse("invoices.html", {"request": request, "invoices": invoices})
    
    except mysql.connector.Error as e:
        # Fallback: Show local JSON files
        print(f"❌ Database connection failed: {e}")
        
        # Find all local JSON files
        import glob
        json_files = glob.glob("invoice_data_*.json")
        invoices = []
        
        for json_file in json_files:
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    data['filename'] = json_file
                    invoices.append(data)
            except Exception as file_error:
                print(f"Error reading {json_file}: {file_error}")
        
        # Return a simple HTML response showing the local data
        html_content = f"""
        <html>
        <head><title>Invoices (Local Files)</title></head>
        <body>
        <h1>Database connection failed. Showing local data:</h1>
        <p>Error: {str(e)}</p>
        <h2>Local Invoice Files:</h2>
        <ul>
        """
        
        for invoice in invoices:
            html_content += f"<li>{invoice.get('filename', 'Unknown')}: Invoice #{invoice.get('M_fe_num', 'N/A')} - Date: {invoice.get('M_fe_date', 'N/A')}</li>"
        
        html_content += """
        </ul>
        <a href="/">Back to Upload</a>
        </body>
        </html>
        """
        
        return HTMLResponse(content=html_content)

# Add database setup endpoint
@app.get("/setup-database/")
async def setup_database():
    try:
        # Connect to MySQL server (without specifying database)
        conn = mysql.connector.connect(
            host='mysql-4791ff0-mohamed-cfcb.c.aivencloud.com',
            port=28974,
            user='avnadmin',
            password='AVNS_awY4JgPDS6TiUUadqdu'
        )
        cursor = conn.cursor()
        
        # Create database
        cursor.execute("CREATE DATABASE IF NOT EXISTS wdoptitransit_khaladi")
        cursor.execute("USE wdoptitransit_khaladi")
        
        # Create invoices table
        invoices_table = """
        CREATE TABLE IF NOT EXISTS invoices (
            id INT AUTO_INCREMENT PRIMARY KEY,
            M_fe_num VARCHAR(255),
            M_fe_date VARCHAR(255),
            M_fe_Pnet DECIMAL(10,3),
            M_fe_Pbrute DECIMAL(10,3),
            M_fe_valDev DECIMAL(10,2),
            dossier_num VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
        cursor.execute(invoices_table)
        
        # Create invoice_items table
        items_table = """
        CREATE TABLE IF NOT EXISTS invoice_items (
            id INT AUTO_INCREMENT PRIMARY KEY,
            invoice_id INT,
            AvecSansPaiment VARCHAR(255),
            M_fl_Ngp VARCHAR(255),
            M_fl_art VARCHAR(255),
            M_fl_desig VARCHAR(255),
            M_fl_orig VARCHAR(255),
            quantity INT,
            M_fl_unite VARCHAR(255),
            M_fl_PNet VARCHAR(255),
            M_fl_PBrut DECIMAL(10,2),
            M_fl_valDev DECIMAL(10,2),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
        )
        """
        cursor.execute(items_table)
        
        # Show tables
        cursor.execute("SHOW TABLES")
        tables = cursor.fetchall()
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return {
            "message": "Database and tables created successfully!",
            "tables": [table[0] for table in tables]
        }
        
    except Exception as e:
        return {
            "error": f"Failed to setup database: {str(e)}",
            "message": "Please check MySQL connection and credentials"
        }

# Add a simple test endpoint for Llama API
@app.get("/test-llama/")
async def test_llama():
    try:
        # Get Llama API URL from environment variable
        llama_api_url = os.environ.get("LLAMA_API_URL", "http://38.46.220.18:5000/api/ask")
        
        headers = {
            "Content-Type": "application/json"
        }
        
        data = {
            "question": "Hello, please respond with a simple JSON: {\"status\": \"working\"}",
            "max_tokens": 100,
            "temperature": 0.1
        }
        
        response = requests.post(
            llama_api_url, 
            headers=headers, 
            json=data,
            timeout=30
        )
        
        return {
            "status_code": response.status_code,
            "response": response.json() if response.status_code == 200 else response.text,
            "api_working": response.status_code == 200
        }
    except Exception as e:
        return {
            "error": str(e),
            "api_working": False
        }

# Add debug endpoint to see what's being received
@app.post("/debug-upload/")
async def debug_upload(request: Request):
    print("🔍 Raw request headers:", dict(request.headers))
    form_data = await request.form()
    print("🔍 Form data keys:", list(form_data.keys()))
    for key, value in form_data.items():
        if hasattr(value, 'filename'):
            print(f"🔍 File field '{key}': filename={value.filename}, content_type={value.content_type}")
        else:
            print(f"🔍 Field '{key}': {value}")
    return {"message": "Debug info logged"}

# Add a simple test endpoint
@app.post("/test-upload/")
async def test_upload():
    print("🔍 TEST ENDPOINT REACHED!")
    return {"message": "Test endpoint working"}

# Upload + OCR + llama+ Save
@app.post("/upload-invoice/", response_class=HTMLResponse)
async def upload_invoice(pdf: UploadFile = File(...), dossier: str = Form(...)):
    print("🔍 UPLOAD ENDPOINT REACHED!")
    print(f"🔍 Debug - Received file: {pdf}")
    print(f"🔍 Debug - Selected dossier: {dossier}")
    print(f"🔍 Debug - File filename: {pdf.filename if pdf else 'None'}")
    print(f"🔍 Debug - File content_type: {pdf.content_type if pdf else 'None'}")
    print(f"🔍 Debug - File size: {pdf.size if pdf and hasattr(pdf, 'size') else 'None'}")
    
    # Validate dossier selection
    if not dossier or dossier.strip() == "":
        raise HTTPException(status_code=400, detail="Numéro de dossier requis. Veuillez sélectionner un dossier.")
    
    # Validate file upload
    if not pdf:
        raise HTTPException(status_code=400, detail="No file object received.")
    
    if not pdf.filename or pdf.filename == "":
        raise HTTPException(status_code=400, detail="No filename provided. Please select a file.")
    
    if pdf.filename == "blob":
        raise HTTPException(status_code=400, detail="Invalid file upload. Please select a proper file.")
    
    # Check file size (optional - limit to 10MB)
    if hasattr(pdf, 'size') and pdf.size and pdf.size > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10MB.")
    
    # Check for zero-byte files (if size is available)
    if hasattr(pdf, 'size') and pdf.size == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded. Please select a valid file.")
    
    # Check file type
    if hasattr(pdf, 'content_type') and pdf.content_type:
        allowed_types = ["application/pdf", "image/png", "image/jpeg", "image/jpg"];
        if pdf.content_type not in allowed_types:
            raise HTTPException(status_code=400, detail=f"Invalid file type: {pdf.content_type}. Only PDF and images (PNG, JPG) are allowed.")
    else:
        print("⚠️ Warning: No content_type available, proceeding with file extension check")
        # Fallback to filename extension check
        if not pdf.filename.lower().endswith(('.pdf', '.png', '.jpg', '.jpeg')):
            raise HTTPException(status_code=400, detail="Invalid file extension. Only PDF and images (PNG, JPG) are allowed.")
    
    try:
        # Read file content
        print("📁 Reading file content...")
        file_content = await pdf.read()
        print(f"📁 File content length: {len(file_content) if file_content else 0} bytes")
        
        if not file_content:
            raise HTTPException(status_code=400, detail="Empty file content. Please select a valid file.")
        
        print(f"✅ Successfully read {len(file_content)} bytes from file: {pdf.filename}")
        
        # Extract text using OCR API
        print("🔍 Starting OCR text extraction...")
        try:
            extracted_text = extract_text_with_custom_ocr(file_content, pdf.filename)
        except Exception as vision_error:
            print(f"❌ OCR processing error: {vision_error}")
            
            # Provide more specific error messages
            error_msg = str(vision_error).lower()
            if "pdf2image" in error_msg or "poppler" in error_msg:
                raise HTTPException(
                    status_code=500, 
                    detail="PDF processing failed. Please ensure pdf2image and poppler-utils are installed. You can try uploading the document as an image instead."
                )
            elif "credentials" in error_msg or "authentication" in error_msg:
                raise HTTPException(
                    status_code=500,
                    detail="OCR API authentication failed. Please check that key.json is properly configured."
                )
            elif "quota" in error_msg or "limit" in error_msg:
                raise HTTPException(
                    status_code=500,
                    detail="OCR API quota exceeded. Please try again later."
                )
            elif "no text found" in error_msg:
                raise HTTPException(
                    status_code=400,
                    detail="No readable text found in the document. Please ensure the document contains clear, readable text."
                )
            else:
                raise HTTPException(
                    status_code=500,
                    detail=f"Text extraction failed: {str(vision_error)}"
                )
        
        if not extracted_text or not extracted_text.strip() or extracted_text.strip() == "No text found.":
            raise HTTPException(status_code=400, detail="No text could be extracted from the document. Please ensure the document contains readable text.")
        
        # Save extracted text for debugging
        save_extracted_text_to_file(extracted_text, "g_output.txt")
        
        print(f"✅ OCR text extraction completed. Extracted {len(extracted_text)} characters")

        # Extract metadata hints for better processing
        metadata = extract_invoice_metadata(extracted_text)
        print(f"🔍 Extracted metadata: {metadata}")
        
        # Debug: Also run manual total detection for extra debugging
        print("🔍 Running debug total detection...")
        debug_totals = debug_total_detection(extracted_text)
        
        # Debug: Show OCR text preview for troubleshooting
        print(f"📄 OCR Text Preview (first 500 chars):")
        print(f"'{extracted_text[:500]}...'")
        print(f"📄 OCR Text Length: {len(extracted_text)} characters")

        parsed_data = {}

        try:
            print("🧠 Starting Llama AI processing...")
            llama_response = parse_invoice_with_llama(extracted_text, metadata)
            print("✅ Raw Llama response:", llama_response)

            # Extract the response content from Llama API
            # Llama API typically returns {"response": "answer"} or {"answer": "answer"}
            assistant_reply = ""
            if isinstance(llama_response, dict):
                assistant_reply = llama_response.get('response', '') or llama_response.get('answer', '') or str(llama_response)
            else:
                assistant_reply = str(llama_response)
                
            if not assistant_reply.strip():
                raise Exception("Llama API returned an empty response.")

            print(f"� Llama response length: {len(assistant_reply)} characters")

            # Handle JSON block
            import re
            match = re.search(r'```(?:json)?\s*([\s\S]+?)\s*```', assistant_reply)
            json_string = match.group(1) if match else assistant_reply.strip()

            try:
                import json
                parsed_data = json.loads(json_string)
            except json.JSONDecodeError as e:
                print(f"❌ Standard JSON decode failed: {e}")
                print(f"🔍 Trying to clean the JSON string...")
                
                # Clean the JSON string more aggressively
                cleaned_json = json_string.strip()
                if cleaned_json.startswith('`'):
                    cleaned_json = cleaned_json.lstrip('`')
                if cleaned_json.endswith('`'):
                    cleaned_json = cleaned_json.rstrip('`')
                if cleaned_json.startswith('json'):
                    cleaned_json = cleaned_json[4:].strip()
                
                # Try to parse the cleaned JSON
                try:
                    parsed_data = json.loads(cleaned_json)
                    print("✅ Successfully parsed JSON after cleaning")
                except json.JSONDecodeError as e2:
                    print(f"❌ Cleaned JSON decode also failed: {e2}")
                    if DEMJSON3_AVAILABLE:
                        print(f"🔍 Trying demjson3 as last resort...")
                        try:
                            # Try to decode using a lenient parser
                            parsed_data = demjson3.decode(cleaned_json)
                            print("✅ Successfully parsed JSON with demjson3")
                        except Exception as e3:
                            print(f"❌ demjson3 also failed: {e3}")
                            print(f"📝 Raw JSON string (first 500 chars): {json_string[:500]}")
                            raise Exception(f"Failed to parse JSON from llama response: {e}")
                    else:
                        print(f"📝 Raw JSON string (first 500 chars): {json_string[:500]}")
                        raise Exception(f"Failed to parse JSON from llama response: {e}")

            # Post-process and validate the parsed data
            parsed_data = post_process_invoice_data(parsed_data, metadata)
            
            # Additional validation for total detection
            if parsed_data.get("M_fe_valDev", 0) == 0.0 and metadata and metadata.get("potential_totals"):
                print("⚠️ Llama didn't extract total, trying to use metadata totals...")
                best_total = 0.0
                for total in metadata["potential_totals"]:
                    try:
                        total_clean = total.replace(",", ".")
                        total_val = float(total_clean)
                        # Prioritize values in reasonable invoice range (50-50000)
                        if 50 <= total_val <= 50000 and total_val > best_total:
                            best_total = total_val
                    except:
                        continue
                
                if best_total > 0:
                    parsed_data["M_fe_valDev"] = best_total
                    print(f"✅ Used metadata total as fallback: {best_total}")
                else:
                    print("⚠️ No valid total found in metadata either")
            else:
                print(f"✅ llama extracted total: {parsed_data.get('M_fe_valDev', 0)}")
            
            print("✅ Parsed and validated JSON from llama.")

            save_to_db(parsed_data, dossier)
            print("✅ Data saved to MySQL.")

        except Exception as e:
            print(f"❌ llamaprocessing error: {e}")
            # Check if it's an API key issue
            if "api key" in str(e).lower() or "authentication" in str(e).lower() or "401" in str(e):
                raise HTTPException(status_code=500, detail="llamaAPI authentication failed. Please check API key.")
            elif "quota" in str(e).lower() or "limit" in str(e).lower():
                raise HTTPException(status_code=500, detail="llamaAPI quota exceeded. Please try again later.")
            else:
                raise HTTPException(status_code=500, detail=f"Failed to parse invoice with llama4: {str(e)}")

        # Fetch dossier details from database
        dossier_data = get_dossier_details(dossier)
        print(f"📋 Dossier data fetched: {dossier_data}")

        template = Template("""
        <html>

<head>
    <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
</head>

<body class="">
    <nav class="bg-[#365D98] text-white">
        <div class="max-w-screen-xl flex flex-wrap items-center justify-between mx-auto p-3">
            <a href="/" class="flex items-center space-x-3 rtl:space-x-reverse">
                <span class="self-center text-2xl font-semibold whitespace-nowrap ">OptimumTransit<span
                        class="ms-1 text-[10px]">OCR</span></span>
            </a>

            <div class="hidden w-full md:block md:w-auto " id="navbar-default">
                <ul
                    class="font-medium flex flex-col p-4 md:p-0 mt-4 border border-gray-100 rounded-lg  md:flex-row md:space-x-8 rtl:space-x-reverse md:mt-0 md:border-0 ">
                   
                    <li>
                        <a href="/invoices" class="block py-2 px-3 text-white rounded-sm md:bg-transparent  md:p-0 "
                            aria-current="page">Historique Des Factures</a>
                    </li>

                </ul>
            </div>
        </div>
    </nav>
    <section class="container mx-auto mt-5 p-5 bg-white  rounded-lg h-[80vh]">

        <h2 class="text-center text-2xl text-[#365D98] font-medium">Résultat de la numérisation</h2>
         <pre class="hidden bg-light p-3 border rounded">{{ parsed_data | tojson(indent=4) }}</pre> 

        <!-- Debug Section (Temporary) -->
        <div class="bg-yellow-50 border border-yellow-300 rounded p-3 mb-4">
            <h4 class="font-semibold text-yellow-800">🔍 Debug Info:</h4>
            <p class="text-sm text-yellow-700">
                Dossier Data Status: {{ "Loaded" if dossier_data else "Not Found" }} | 
                {% if dossier_data %}
                    Fields: {{ dossier_data.keys() | list | length }} | 
                    Dossier: {{ dossier_data['M_Ds_Num'] if dossier_data.get('M_Ds_Num') else 'No Number' }}
                {% else %}
                    No dossier data available
                {% endif %}
            </p>
        </div>

        <!-- Enhanced Dossier Information Section -->
        <div class="bg-blue-50 border border-blue-200 rounded-lg p-4 mt-6">
            <h3 class="text-lg font-semibold text-[#365D98] mb-4">📋 Informations du Dossier</h3>
            
            <!-- Row 1: Basic Info -->
            <div class="grid grid-cols-4 gap-4 mb-4">
                <div class="flex flex-col">
                    <label class="text-sm font-medium text-gray-600 mb-1">N° Dossier</label>
                    <input class="bg-white border border-gray-300 rounded px-3 py-2 text-gray-700 font-semibold"
                           type="text" value="{{ dossier_data['M_Ds_Num'] if dossier_data else '' }}" readonly>
                </div>
                <div class="flex flex-col">
                    <label class="text-sm font-medium text-gray-600 mb-1">N° DUM</label>
                    <input class="bg-white border border-gray-300 rounded px-3 py-2 text-gray-700"
                           type="text" value="{{ dossier_data['M_Ds_ndum'] if dossier_data else '' }}" readonly>
                </div>
                <div class="flex flex-col">
                    <label class="text-sm font-medium text-gray-600 mb-1">Date Dossier</label>
                    <input class="bg-white border border-gray-300 rounded px-3 py-2 text-gray-700"
                           type="text" value="{{ dossier_data['M_Ds_date'] if dossier_data else '' }}" readonly>
                </div>
                <div class="flex flex-col">
                    <label class="text-sm font-medium text-gray-600 mb-1">Statut</label>
                    <input class="bg-white border border-gray-300 rounded px-3 py-2 text-gray-700"
                           type="text" value="{{ dossier_data['M_Ds_Statut'] if dossier_data else '' }}" readonly>
                </div>
            </div>
            
            <!-- Row 2: Trade Info -->
            <div class="grid grid-cols-4 gap-4 mb-4">
                <div class="flex flex-col">
                    <label class="text-sm font-medium text-gray-600 mb-1">Incoterm</label>
                    <input class="bg-white border border-gray-300 rounded px-3 py-2 text-gray-700"
                           type="text" value="{{ dossier_data['M_Ds_Inco'] if dossier_data else '' }}" readonly>
                </div>
                <div class="flex flex-col">
                    <label class="text-sm font-medium text-gray-600 mb-1">Devise</label>
                    <input class="bg-white border border-gray-300 rounded px-3 py-2 text-gray-700"
                           type="text" value="{{ dossier_data['M_Ds_devise'] if dossier_data else '' }}" readonly>
                </div>
                <div class="flex flex-col">
                    <label class="text-sm font-medium text-gray-600 mb-1">Cours</label>
                    <input class="bg-white border border-gray-300 rounded px-3 py-2 text-gray-700"
                           type="text" value="{{ '%.4f'|format(dossier_data['M_Ds_cours']) if dossier_data and dossier_data['M_Ds_cours'] else '' }}" readonly>
                </div>
                <div class="flex flex-col">
                    <label class="text-sm font-medium text-gray-600 mb-1">Origine</label>
                    <input class="bg-white border border-gray-300 rounded px-3 py-2 text-gray-700"
                           type="text" value="{{ dossier_data['M_Ds_Orig'] if dossier_data else '' }}" readonly>
                </div>
            </div>
            
            <!-- Row 3: Shipping Info -->
            <div class="grid grid-cols-3 gap-4 mb-4">
                <div class="flex flex-col">
                    <label class="text-sm font-medium text-gray-600 mb-1">Navire</label>
                    <input class="bg-white border border-gray-300 rounded px-3 py-2 text-gray-700"
                           type="text" value="{{ dossier_data['M_Ds_navire'] if dossier_data else '' }}" readonly>
                </div>
                <div class="flex flex-col">
                    <label class="text-sm font-medium text-gray-600 mb-1">Conteneur</label>
                    <input class="bg-white border border-gray-300 rounded px-3 py-2 text-gray-700"
                           type="text" value="{{ dossier_data['M_Ds_cnt'] if dossier_data else '' }}" readonly>
                </div>
                <div class="flex flex-col">
                    <label class="text-sm font-medium text-gray-600 mb-1">N° Manifeste</label>
                    <input class="bg-white border border-gray-300 rounded px-3 py-2 text-gray-700"
                           type="text" value="{{ dossier_data['M_Ds_NumManifeste'] if dossier_data else '' }}" readonly>
                </div>
            </div>
            
            <!-- Row 4: Weights and Values -->
            <div class="grid grid-cols-4 gap-4 mb-4">
                <div class="flex flex-col">
                    <label class="text-sm font-medium text-gray-600 mb-1">Poids Net (kg)</label>
                    <input class="bg-white border border-gray-300 rounded px-3 py-2 text-gray-700 font-semibold"
                           type="text" value="{{ '%.2f'|format(dossier_data['M_Ds_Pnet']) if dossier_data and dossier_data['M_Ds_Pnet'] else '' }}" readonly>
                </div>
                <div class="flex flex-col">
                    <label class="text-sm font-medium text-gray-600 mb-1">Poids Brut (kg)</label>
                    <input class="bg-white border border-gray-300 rounded px-3 py-2 text-gray-700 font-semibold"
                           type="text" value="{{ '%.2f'|format(dossier_data['M_Ds_Pbrut']) if dossier_data and dossier_data['M_Ds_Pbrut'] else '' }}" readonly>
                </div>
                <div class="flex flex-col">
                    <label class="text-sm font-medium text-gray-600 mb-1">Nombre Colis</label>
                    <input class="bg-white border border-gray-300 rounded px-3 py-2 text-gray-700"
                           type="text" value="{{ dossier_data['M_Ds_Ncolis'] if dossier_data else '' }}" readonly>
                </div>
                <div class="flex flex-col">
                    <label class="text-sm font-medium text-gray-600 mb-1">Montant Fret</label>
                    <input class="bg-white border border-gray-300 rounded px-3 py-2 text-gray-700 font-semibold"
                           type="text" value="{{ '%.2f'|format(dossier_data['M_Ds_Mtfret']) if dossier_data and dossier_data['M_Ds_Mtfret'] else '' }}" readonly>
                </div>
            </div>
            
            <!-- Row 5: Client and Customs Info -->
            <div class="grid grid-cols-3 gap-4">
                <div class="flex flex-col">
                    <label class="text-sm font-medium text-gray-600 mb-1">Code Client</label>
                    <input class="bg-white border border-gray-300 rounded px-3 py-2 text-gray-700"
                           type="text" value="{{ dossier_data['M_Ds_CodeClient'] if dossier_data else '' }}" readonly>
                </div>
                <div class="flex flex-col">
                    <label class="text-sm font-medium text-gray-600 mb-1">Bureau Douane</label>
                    <input class="bg-white border border-gray-300 rounded px-3 py-2 text-gray-700"
                           type="text" value="{{ dossier_data['M_DS_Bureau'] if dossier_data else '' }}" readonly>
                </div>
                <div class="flex flex-col">
                    <label class="text-sm font-medium text-gray-600 mb-1">Régime Douanier</label>
                    <input class="bg-white border border-gray-300 rounded px-3 py-2 text-gray-700"
                           type="text" value="{{ dossier_data['M_DS_Regime'] if dossier_data else '' }}" readonly>
                </div>
            </div>
            
            {% if dossier_data and dossier_data['M_Ds_Designation'] %}
            <div class="mt-4">
                <label class="text-sm font-medium text-gray-600 mb-1 block">Désignation</label>
                <textarea class="bg-white border border-gray-300 rounded px-3 py-2 text-gray-700 w-full" 
                          rows="2" readonly>{{ dossier_data['M_Ds_Designation'] }}</textarea>
            </div>
            {% endif %}
        </div>

        <div class="grid grid-cols-3 w-full mt-6">
            <div class="border-2 rounded border-gray-300 px-2 py-4">

                <div class="md:flex md:items-center mb-6 col-span-1 ">
                    <div class="w-1/3">
                        <label class="block text-gray-500 font-bold md:text-right mb-1 md:mb-0 pr-4"
                            for="numFact">
                            N° Facture <span class="text-red-700">*</span>
                        </label>
                    </div>
                    <div class="">
                        <input
                            class="bg-gray-200 appearance-none border-2 border-gray-200 rounded w-full py-2 px-4 text-gray-700 leading-tight focus:outline-none focus:bg-white focus:border-[#365D98]"
                            id="numFact" type="text" value="{{parsed_data['M_fe_num'] or 'À COMPLETER'}}" placeholder="Numéro de facture requis">
                    </div>
                </div>
                <div class="md:flex md:items-center  col-span-1">
                    <div class="w-1/3">
                        <label class="block text-gray-500 font-bold md:text-right mb-1 md:mb-0 pr-4"
                            for="inline-full-name">
                            Date Facture <span class="text-red-700">*</span>
                        </label>
                    </div>
                    <div class="">
                        <input
                            class="bg-gray-200 appearance-none border-2 border-gray-200 rounded w-full py-2 px-4 text-gray-700 leading-tight focus:outline-none focus:bg-white focus:border-[#365D98]"
                            id="inline-full-name" type="text" value="{{parsed_data['M_fe_date'] or 'À COMPLETER'}}" placeholder="Date requise">
                    </div>
                </div>
            </div>
            <div class="border-2 rounded border-gray-300 px-2 py-4 ms-2">

                <div class="md:flex md:items-center mb-6 col-span-1">
                    <div class="w-1/3">
                        <label class="block text-gray-500 font-bold md:text-right mb-1 md:mb-0 pr-4"
                            for="inline-full-name">
                            Incoterm
                        </label>
                    </div>
                    <div class="">
                        <input
                            class="bg-gray-200 appearance-none border-2 border-gray-200 rounded w-full py-2 px-4 text-gray-700 leading-tight focus:outline-none focus:bg-white focus:border-[#365D98]"
                            id="inline-full-name" type="text" value="{{ dossier_data['M_Ds_Inco'] if dossier_data else '' }}"  >
                    </div>
                </div>
                <div class="md:flex md:items-center  col-span-1">
                    <div class="w-1/3">
                        <label class="block text-gray-500 font-bold md:text-right mb-1 md:mb-0 pr-4"
                            for="inline-full-name">
                            Montant Fret
                        </label>
                    </div>
                    <div class="">
                        <input
                            class="bg-gray-200 appearance-none border-2 border-gray-200 rounded w-full py-2 px-4 text-gray-700 leading-tight focus:outline-none focus:bg-white focus:border-[#365D98]"
                            id="inline-full-name" type="text" value="{{ dossier_data['M_Ds_Mtfret'] if dossier_data else '' }}"  >
                    </div>
                </div>
            </div>
            <div class="border-2 rounded border-gray-300 px-2 py-4 ms-2">

                <div class="md:flex md:items-center mb-6 col-span-1">
                    <div class="w-1/3">
                        <label class="block text-gray-500 font-bold md:text-right mb-1 md:mb-0 pr-4"
                            for="inline-full-name">
                            Code Exportateur
                        </label>
                    </div>
                    <div class="">
                        <input
                            class="bg-gray-200 appearance-none border-2 border-gray-200 rounded w-full py-2 px-4 text-gray-700 leading-tight focus:outline-none focus:bg-white focus:border-[#365D98]"
                            id="inline-full-name" type="text" value=""  >
                    </div>
                </div>
                <div class="md:flex md:items-center  col-span-1">
                    <div class="w-1/3">
                        <label class="block text-gray-500 font-bold md:text-right mb-1 md:mb-0 pr-4"
                            for="inline-full-name">
                            Nom Exportateur
                        </label>
                    </div>
                    <div class="">
                        <input
                            class="bg-gray-200 appearance-none border-2 border-gray-200 rounded w-full py-2 px-4 text-gray-700 leading-tight focus:outline-none focus:bg-white focus:border-[#365D98]"
                            id="inline-full-name" type="text" value=""  >
                    </div>
                </div>
            </div>

        </div>
        <div class="grid grid-cols-3 w-full mt-10">
            <div class="border-2 rounded border-gray-300 px-2 py-4 ">

                <div class="md:flex md:items-center mb-6 col-span-1">
                    <div class="w-1/3">
                        <label class="block text-gray-500 font-bold md:text-right mb-1 md:mb-0 pr-4"
                            for="inline-full-name">
                            Devise
                        </label>
                    </div>
                    <div class="">
                        <input
                            class="bg-gray-200 appearance-none border-2 border-gray-200 rounded w-full py-2 px-4 text-gray-700 leading-tight focus:outline-none focus:bg-white focus:border-[#365D98]"
                            id="inline-full-name" type="text" value="{{parsed_data['M_fe_devise'] or 'MAD'}}"  >
                    </div>
                </div>
                <div class="md:flex md:items-center  col-span-1">
                    <div class="w-1/3">
                        <label class="block text-gray-500 font-bold md:text-right mb-1 md:mb-0 pr-4"
                            for="inline-full-name">
                            Cours
                        </label>
                    </div>
                    <div class="">
                        <input
                            class="bg-gray-200 appearance-none border-2 border-gray-200 rounded w-full py-2 px-4 text-gray-700 leading-tight focus:outline-none focus:bg-white focus:border-[#365D98]"
                            id="inline-full-name" type="text" value="{{ '%.4f'|format(dossier_data['M_Ds_cours']) if dossier_data and dossier_data['M_Ds_cours'] else '' }}"  >
                    </div>
                </div>
            </div>
            <div class="border-2 rounded border-gray-300 px-2 py-4 ms-2">

                <div class="md:flex md:items-center mb-6 col-span-1">
                    <div class="w-1/3">
                        <label class="block text-gray-500 font-bold md:text-right mb-1 md:mb-0 pr-4"
                            for="inline-full-name">
                            Poid Net <span class="text-red-700">*</span>
                        </label>
                    </div>
                    <div class="">
                        <input
                            class="bg-gray-200 appearance-none border-2 border-gray-200 rounded w-full py-2 px-4 text-gray-700 leading-tight focus:outline-none focus:bg-white focus:border-[#365D98]"
                            id="inline-full-name" type="text" value="{{parsed_data['M_fe_Pnet']}}"  >
                    </div>
                </div>
                <div class="md:flex md:items-center col-span-1">
                    <div class="w-1/3">
                        <label class="block text-gray-500 font-bold md:text-right mb-1 md:mb-0 pr-4"
                            for="inline-full-name">
                            Nombre Colis
                        </label>
                    </div>
                    <div class="">
                        <input
                            class="bg-gray-200 appearance-none border-2 border-gray-200 rounded w-full py-2 px-4 text-gray-700 leading-tight focus:outline-none focus:bg-white focus:border-[#365D98]"
                            id="inline-full-name" type="text" value=""  >
                    </div>
                </div>
            </div>
            <div class="border-2 rounded border-gray-300 px-2 py-4 ms-2">

                <div class="md:flex md:items-center mb-6 col-span-1">
                    <div class="w-1/3">
                        <label class="block text-gray-500 font-bold md:text-right mb-1 md:mb-0 pr-4"
                            for="inline-full-name">
                            Poids brut <span class="text-red-700">*</span>
                        </label>
                    </div>
                    <div class="">
                        <input
                            class="bg-gray-200 appearance-none border-2 border-gray-200 rounded w-full py-2 px-4 text-gray-700 leading-tight focus:outline-none focus:bg-white focus:border-[#365D98]"
                            id="inline-full-name" type="text" value="{{parsed_data['M_fe_Pbrute']}}"  >
                    </div>
                </div>
                <div class="md:flex md:items-center  col-span-1">
                    <div class="w-1/3">
                        <label class="block text-gray-500 font-bold md:text-right mb-1 md:mb-0 pr-4"
                            for="inline-full-name">
                            Valeur devise <span class="text-red-700">*</span>
                        </label>
                    </div>
                    <div class="">
                        <input
                            class="bg-gray-200 appearance-none border-2 border-gray-200 rounded w-full py-2 px-4 text-gray-700 leading-tight focus:outline-none focus:bg-white focus:border-[#365D98]"
                            id="inline-full-name" type="text" value="{{parsed_data['M_fe_valDev']}}"  >
                    </div>
                </div>
            </div>

        </div>
        
        <!-- Summary Section -->
        <div class="mt-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
            <h3 class="text-lg font-semibold text-[#365D98] mb-3">Totaux Calculés</h3>
            <div class="grid grid-cols-3 gap-4">
                <div class="text-center">
                    <label class="block text-sm font-medium text-gray-600">Poids Net Total</label>
                    <span class="text-xl font-bold text-[#365D98]">{{parsed_data['M_fe_Pnet']}} kg</span>
                </div>
                <div class="text-center">
                    <label class="block text-sm font-medium text-gray-600">Poids Brut Total</label>
                    <span class="text-xl font-bold text-[#365D98]">{{parsed_data['M_fe_Pbrute']}} kg</span>
                </div>
                <div class="text-center">
                    <label class="block text-sm font-medium text-gray-600">Valeur Totale</label>
                    <span class="text-xl font-bold text-[#365D98]">{{parsed_data['M_fe_valDev']}} DH</span>
                </div>
            </div>
            <div class="mt-3 text-center">
                <span class="text-sm text-gray-600">Nombre d'articles: {{parsed_data['items']|length}}</span>
            </div>
        </div>
        
        <table  
        
            class="table-auto border-collapse border border-gray-300 w-full mt-10 rounded-lg overflow-hidden">
            <thead class="bg-[#365D98] text-white">
                <tr>
                    <th class="border border-gray-300 px-4 py-2">Nomenclature</th>
                    <th class="border border-gray-300 px-4 py-2">Article</th>
                    <th class="border border-gray-300 px-4 py-2">Designation</th>
                    <th class="border border-gray-300 px-4 py-2">Origine</th>
                    <th class="border border-gray-300 px-4 py-2">Quantité</th>
                    <th class="border border-gray-300 px-4 py-2">Unité</th>
                    <th class="border border-gray-300 px-4 py-2">Poids Net</th>
                    <th class="border border-gray-300 px-4 py-2">Valeur Devise</th>
                </tr>
            </thead>
            <tbody>
                           
                {% for item in parsed_data['items'] %}
                            
                <tr>
                    <td class="border border-gray-300 px-4 py-2 relative">
                        <input type="text" 
                               class="ngp-input w-full border-2 border-gray-100 rounded px-2 py-1 focus:outline-none focus:border-[#365D98] {% if not item['M_fl_Ngp'] or item['M_fl_Ngp'] == 'CODE REQUIS' %}bg-yellow-50 border-yellow-300{% endif %}"
                               value="{{ item['M_fl_Ngp'] if item['M_fl_Ngp'] and item['M_fl_Ngp'] != '' else 'CODE REQUIS' }}" 
                               placeholder="Code NGP requis"
                               data-row="{{ loop.index0 }}"
                               autocomplete="off">
                        <div class="ngp-dropdown absolute top-full left-0 w-full bg-white border border-gray-300 rounded-b max-h-48 overflow-y-auto shadow-lg z-10 hidden"></div>
                    </td>
                    <td class="border border-gray-300 px-4 py-2">
                        <input type="text" class="w-full border-2 border-gray-100 rounded px-2 py-1 focus:outline-none focus:border-[#365D98]"
                            value="{{ item['M_fl_art'] or '' }}" placeholder="Code article">
                    </td>
                    <td class="border border-gray-300 px-4 py-2">
                        <input type="text" class="w-full border-2 border-gray-100 rounded px-2 py-1 focus:outline-none focus:border-[#365D98]"
                            value="{{ item['M_fl_desig'] or '' }}" placeholder="Désignation">
                    </td>
                    <td class="border border-gray-300 px-4 py-2">
                        <input type="text" class="w-full border-2 border-gray-100 rounded px-2 py-1 focus:outline-none focus:border-[#365D98]"
                            value="{{ item['M_fl_orig'] if item['M_fl_orig'] else 'MAROC' }}" placeholder="Pays d'origine">
                    </td>
                    <td class="border border-gray-300 px-4 py-2">
                        <input type="text" class="w-full border-2 border-gray-100 rounded px-2 py-1 focus:outline-none focus:border-[#365D98]"
                            value="{{ item['quantity'] or 1 }}">
                    </td>
                    <td class="border border-gray-300 px-4 py-2">
                        <input type="text" class="w-full border-2 border-gray-100 rounded px-2 py-1 focus:outline-none focus:border-[#365D98]"
                            value="{{ item['M_fl_unite'] or 'Pièce' }}">
                    </td>
                    <td class="border border-gray-300 px-4 py-2">
                        <input type="text" class="w-full border-2 border-gray-100 rounded px-2 py-1 focus:outline-none focus:border-[#365D98]"
                            value="{{ item['M_fl_PNet'] if item['M_fl_PNet'] != 0 else '0' }}">
                    </td>
                    <td class="border border-gray-300 px-4 py-2">
                        <input type="text" class="w-full border-2 border-gray-100 rounded px-2 py-1 focus:outline-none focus:border-[#365D98] font-semibold"
                            value="{{ '%.2f'|format(item['M_fl_valDev']) if item['M_fl_valDev'] else '0.00' }}">
                    </td>
                </tr>
                {% endfor %} 

            </tbody>
        </table>
        <div class="text-center mt-4">
            <a href="/" class="rounded bg-gray-200 px-2 py-1.5">Télécharger un autre</a>
            <a href="/invoices" class="rounded bg-gray-200 px-2 py-1.5">Voir toutes les factures</a>
        </div>
    </section>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // NGP Autocomplete functionality
            const ngpInputs = document.querySelectorAll('.ngp-input');
            let ngpCache = [];
            let activeDropdown = null;

            // Function to fetch NGP codes
            async function fetchNGPCodes(searchTerm) {
                try {
                    const response = await fetch(`/search-ngp/?q=${encodeURIComponent(searchTerm)}`);
                    const data = await response.json();
                    return data.ngp_codes || [];
                } catch (error) {
                    console.error('Error fetching NGP codes:', error);
                    return [];
                }
            }

            // Function to show dropdown
            function showDropdown(input, ngpCodes) {
                const dropdown = input.nextElementSibling;
                dropdown.innerHTML = '';
                
                if (ngpCodes.length === 0) {
                    dropdown.innerHTML = '<div class="px-3 py-2 text-gray-500">Aucun code trouvé</div>';
                } else {
                    ngpCodes.forEach(ngp => {
                        const item = document.createElement('div');
                        item.className = 'px-3 py-2 hover:bg-blue-50 cursor-pointer border-b border-gray-100';
                        item.innerHTML = `
                            <div class="font-medium text-blue-600">${ngp.code_ngp}</div>
                            <div class="text-sm text-gray-600">${ngp.designation || 'Sans description'}</div>
                        `;
                        item.onclick = () => {
                            input.value = ngp.code_ngp;
                            input.classList.remove('bg-yellow-50', 'border-yellow-300');
                            dropdown.classList.add('hidden');
                            activeDropdown = null;
                        };
                        dropdown.appendChild(item);
                    });
                }
                
                dropdown.classList.remove('hidden');
                activeDropdown = dropdown;
            }

            // Function to hide dropdown
            function hideDropdown(dropdown) {
                if (dropdown) {
                    dropdown.classList.add('hidden');
                    activeDropdown = null;
                }
            }

            // Add event listeners to all NGP inputs
            ngpInputs.forEach(input => {
                let debounceTimer;
                
                input.addEventListener('focus', function(e) {
                    // If field has a real NGP code from Llama, show it and allow editing
                    const currentValue = e.target.value.trim();
                    if (currentValue && currentValue !== 'CODE REQUIS') {
                        // Show dropdown with current search if it's a partial code
                        if (currentValue.length >= 2) {
                            fetchNGPCodes(currentValue).then(ngpCodes => {
                                showDropdown(this, ngpCodes);
                            });
                        }
                    }
                });

                input.addEventListener('input', function(e) {
                    clearTimeout(debounceTimer);
                    const searchTerm = e.target.value.trim();
                    
                    // If user is typing, clear the placeholder styling
                    if (searchTerm && searchTerm !== 'CODE REQUIS') {
                        e.target.classList.remove('bg-yellow-50', 'border-yellow-300');
                    }
                    
                    if (searchTerm.length < 2 || searchTerm === 'CODE REQUIS') {
                        hideDropdown(this.nextElementSibling);
                        return;
                    }
                    
                    debounceTimer = setTimeout(async () => {
                        const ngpCodes = await fetchNGPCodes(searchTerm);
                        showDropdown(this, ngpCodes);
                    }, 300);
                });

                input.addEventListener('blur', function(e) {
                    // Delay hiding to allow click on dropdown
                    setTimeout(() => {
                        // Only restore placeholder if field is empty
                        if (!e.target.value.trim()) {
                            e.target.value = 'CODE REQUIS';
                            e.target.classList.add('bg-yellow-50', 'border-yellow-300');
                        } else if (e.target.value.trim() === 'CODE REQUIS') {
                            e.target.classList.add('bg-yellow-50', 'border-yellow-300');
                        }
                        hideDropdown(this.nextElementSibling);
                    }, 200);
                });
            });

            // Hide dropdown when clicking outside
            document.addEventListener('click', function(e) {
                if (!e.target.closest('.ngp-input') && !e.target.closest('.ngp-dropdown')) {
                    if (activeDropdown) {
                        hideDropdown(activeDropdown);
                    }
                }
            });
        });
    </script>
</body>

</html>
        """)
        return template.render(parsed_data=parsed_data, dossier_data=dossier_data)

    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"OCR error: {str(e)}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")
    finally:
        # Keep the OCR text file for debugging/review
        if os.path.exists("goutput.txt"):
            print(f"📄 OCR text file preserved: output.txt")


if __name__ == "__main__":
    # Test the OCR API with available test files
    test_files = ["image.png", "test.pdf", "sample.jpg"]
    
    for test_file in test_files:
        if os.path.exists(test_file):
            print(f"🔍 Testing OCR API with {test_file}...")
            try:
                with open(test_file, "rb") as f:
                    content = f.read()
                text = extract_text_with_custom_ocr(content, test_file)
                print(f"✅ OCR test successful for {test_file}!")
                print(f"Extracted text preview: {text[:200]}...")
                
                # Save test output
                output_filename = f"custom_ocr_test_output_{os.path.splitext(test_file)[0]}.txt"
                save_extracted_text_to_file(text, output_filename)
                break  # Test with first available file only
            except Exception as e:
                print(f"❌ OCR test failed for {test_file}: {e}")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)