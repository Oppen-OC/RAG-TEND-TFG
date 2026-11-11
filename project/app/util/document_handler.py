import json
import requests
from odf.opendocument import load
from odf.text import P
from docx import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
import os
import pdfplumber
import re
from tqdm import tqdm

def idDocType(title):
    parts = title.split('.')
    return parts[-1] if parts else None

def preprocess_text(text):
    replacements = {
        "Nº": "Número",
        "nº": "Número",
        "☒": "[SELECCIONADO]",
        "x□": "[SELECCIONADO]",
        "X□": "[SELECCIONADO]",
        "\nX": "[SELECCIONADO]"
    }
        
    # Realizar los reemplazos iniciales
    for old, new in replacements.items():
        text = text.replace(old, new)  

    if "[SELECCIONADO]" in text:
        replacements_1 = {        
            "□": "[NO SELECCIONADO]",
            "☐": "[NO SELECCIONADO]"
        }

        for old, new in replacements_1.items():
            text = text.replace(old, new)

    # Eliminar texto seguido por [NO SELECCIONADO] hasta un salto de línea o [SELECCIONADO]
    pattern = r"\[NO SELECCIONADO\].*?(?=\n|\[SELECCIONADO\])"
    text = re.sub(pattern, "", text, flags=re.DOTALL)

    # Eliminar información dentro de paréntesis que contenga "art."
    pattern_art = r"\([^)]*?art\.[^)]*?\)"
    text = re.sub(pattern_art, "", text)

    return text

def section_identifier(text, anterior):
    """
    :param text: Texto a analizar.
    :param anterior: Última sección identificada previamente.
    :return: Lista de secciones identificadas.
    """
    # Expresión regular para detectar letras seguidas de ". " o "APARTADO X\n"
    pattern = r"(?:^|\n)[A-ZÑ]{1}\. |(?:^|\n)APARTADO [A-ZÑ]{1}\n|(?:^|\n)(?:I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII|XIII|XIV|XV|XVI|XVII|XVIII|XIX|XX|XXI|XXII|XXIII|XXIV|XXV|XXVI|XXVII|XXVIII|XXIX|XXX)\. "    
    secciones = re.findall(pattern, text)  # Encuentra todas las coincidencias
    ans = [anterior] if anterior else []
    
    for seccion in secciones:
        seccion = seccion.replace("\n", "").replace(".", "").strip()  # Elimina saltos de línea, puntos y espacios
        if "APARTADO" in seccion:
            # Si contiene "APARTADO", quedarse con el último carácter
            seccion = seccion[-1]
        if seccion not in ans:
            ans.append(seccion)
    
    return ans

def spliter(ant, text, size = 800, overlap=400):
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=size,chunk_overlap=overlap)
    texts = text_splitter.split_text(ant)
    texts[-1] = texts[-1] + text[:overlap]
    return texts

def download_to_json(url):
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))  # Base directory
        output_dir = os.path.join(base_dir, 'temp_files')  # Output directory

        os.makedirs(output_dir, exist_ok=True)

        # Download the document
        response = requests.get(url)
        response.raise_for_status()

        # Obtener el nombre del archivo del encabezado Content-Disposition
        content_disposition = response.headers.get('Content-Disposition')
        if content_disposition:
            # Extraer el nombre del archivo del encabezado
            filename = content_disposition.split('filename=')[-1].strip('"')

        file_type = idDocType(filename)  # Get the file type from the filename

        # Save the document temporarily
        temp_doc_path = os.path.join(output_dir, f"temp_document.{file_type}")
        with open(temp_doc_path, 'wb') as temp_doc_file:
            temp_doc_file.write(response.content)

        # Extract text and metadata
        data = []  # List to store text and metadata
        if file_type == 'odt':
            doc = load(temp_doc_path)
            paragraphs = [str(para) for para in doc.getElementsByType(P)]
            for i, para in enumerate(paragraphs):
                data.append({"page": i + 1, "text": para})

        elif file_type == 'docx':
            doc = Document(temp_doc_path)
            paragraphs = [para.text for para in doc.paragraphs]
            for i, para in enumerate(paragraphs):
                data.append({"page": i + 1, "text": para})

        elif file_type == 'pdf':
            with pdfplumber.open(temp_doc_path) as pdf:
                ant_text = ""
                ant_table = None
                ant_sec = None
                for i, page in enumerate(tqdm(pdf.pages, desc="Processing pages", unit="page")):
                    size = (0.05 * page.width, 0.05 * page.height, 0.95 * page.width, 0.95 * page.height)
                    cropped_page = page.crop(size)
                    text = cropped_page.extract_text()
                    text = preprocess_text(text)  # Preprocess the text

                    # Extract sections based on page number
                    if data:
                        sec = section_identifier(text, data[-1]["sections"][-1])
                    else:
                        sec = section_identifier(text, "None")

                    if ant_text != "":
                        chunks = spliter(ant_text, text)  # Perform semantic chunking                   
                        data.append({"page": page.page_number -1, "chunks": chunks, "text": ant_text, "tables": ant_table,"sections": ant_sec})    
                        ant_text = text       
                        ant_table = cropped_page.extract_table()   
                        ant_sec = section_identifier(text, data[-1]["sections"][-1])
                    else: 
                        ant_text = text  
                        ant_table = cropped_page.extract_table()
                        ant_sec = sec
                    
                    if i == len(pdf.pages) - 1:
                        chunks = spliter(ant_text, "")
                        data.append({"page": page.page_number , "chunks": chunks , "text": ant_text, "tables": ant_table,"sections": ant_sec})
                    

        elif file_type == "zip":
            print("Compatibilidad con .zip aun no implementada")
            return None
        else:
            print(f"Tipo de archivo no soportado: {file_type}")
            return None

        # Save the extracted data to a JSON file
        json_file_path = os.path.join(output_dir, "temp_document.json")
        with open(json_file_path, 'w', encoding='utf-8') as json_file:
            json.dump(data, json_file, ensure_ascii=False, indent=4)

        print(f"JSON file saved to: {json_file_path}")
        return json_file_path

    except requests.RequestException as e:
        print(f"Error al descargar el documento: {e}")
        return None
    except Exception as e:
        print(f"Error al convertir el documento a JSON: {e}")
        return None
