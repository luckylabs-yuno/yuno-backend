# services/content_processor.py
# NEW FILE - Create this in your services folder

import json
import hashlib
import time
from typing import Dict, List, Optional
from datetime import datetime
import PyPDF2
import docx
import openai
from supabase import Client
import logging

logger = logging.getLogger(__name__)

class ContentProcessor:
    """Service for processing uploaded content (text/files) for RAG"""
    
    def __init__(self, supabase_client: Client, openai_api_key: str):
        self.supabase = supabase_client
        openai.api_key = openai_api_key
        self.chunk_size = 500
        self.chunk_overlap = 100
        
    def process_contact_info(self, site_id: str, contact_info: Dict) -> bool:
        """
        Save contact information to custom_detail table
        """
        try:
            # Build site_prompt from contact info
            prompt_parts = []
            
            if contact_info.get('supportEmail'):
                prompt_parts.append(f"Support Email: {contact_info['supportEmail']}")
            if contact_info.get('companyName'):
                prompt_parts.append(f"Company: {contact_info['companyName']}")
            if contact_info.get('phone'):
                prompt_parts.append(f"Phone: {contact_info['phone']}")
            if contact_info.get('contactName'):
                prompt_parts.append(f"Contact Person: {contact_info['contactName']}")
            if contact_info.get('address'):
                prompt_parts.append(f"Address: {contact_info['address']}")
            
            site_prompt = "When users need support or want to contact the company, provide this information:\n" + "\n".join(prompt_parts)
            
            # Check if record exists
            existing = self.supabase.table('custom_detail')\
                .select('id')\
                .eq('site_id', site_id)\
                .execute()
            
            if existing.data:
                # Update existing
                self.supabase.table('custom_detail')\
                    .update({'site_prompt': site_prompt})\
                    .eq('site_id', site_id)\
                    .execute()
            else:
                # Create new
                self.supabase.table('custom_detail')\
                    .insert({
                        'site_id': site_id,
                        'site_prompt': site_prompt
                    })\
                    .execute()
            
            logger.info(f"Updated contact info for site {site_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating contact info: {str(e)}")
            return False
    
    def process_text_content(self, site_id: str, text: str, upload_id: str) -> Dict:
        """
        Process raw text: chunk, embed, and store in snappi_chunks
        """
        try:
            # Clean text
            clean_text = " ".join(text.strip().split())
            
            # Get summary and tags
            summary_info = self._get_summary_and_tags(clean_text)
            
            # Chunk text
            chunks = self._chunk_text(clean_text)
            processed_count = 0
            
            for idx, chunk in enumerate(chunks):
                if len(chunk.split()) < 20:  # Skip small chunks
                    continue
                    
                try:
                    # Get embedding
                    embedding = self._get_embedding(chunk)
                    chunk_id = hashlib.md5(f"{site_id}_text_{upload_id}_{idx}".encode()).hexdigest()
                    
                    # Insert to snappi_chunks
                    self.supabase.table('snappi_chunks').insert({
                        'id': chunk_id,
                        'url': f"custom_content_{upload_id}",
                        'section': 'custom_text',
                        'chunk_index': idx,
                        'text': chunk,
                        'embedding': embedding,
                        'title': 'User Provided Content',
                        'summary': summary_info.get('summary', ''),
                        'tags': summary_info.get('tags', []),
                        'site_id': site_id,
                        'lang': 'en',
                        'scraped_ok': True,
                        'page_hash': hashlib.md5(clean_text.encode()).hexdigest(),
                        'created_at': datetime.utcnow().isoformat()
                    }).execute()
                    
                    processed_count += 1
                    
                except Exception as e:
                    logger.error(f"Error processing chunk {idx}: {e}")
                    continue
            
            return {
                'success': True,
                'chunks_processed': processed_count,
                'total_chunks': len(chunks)
            }
            
        except Exception as e:
            logger.error(f"Error processing text content: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def process_file_upload(self, site_id: str, file_path: str, file_name: str, upload_id: str) -> Dict:
        """
        Process uploaded file: extract text, chunk, embed, and store
        """
        try:
            # Download file from Supabase storage
            file_data = self.supabase.storage.from_('content-uploads').download(file_path)
            
            # Extract text based on file type
            if file_name.lower().endswith('.pdf'):
                text = self._extract_pdf_text(file_data)
            elif file_name.lower().endswith(('.doc', '.docx')):
                text = self._extract_doc_text(file_data)
            elif file_name.lower().endswith('.txt'):
                text = file_data.decode('utf-8')
            else:
                raise ValueError(f"Unsupported file type: {file_name}")
            
            if not text:
                raise ValueError("No text content extracted from file")
            
            # Get summary and tags
            summary_info = self._get_summary_and_tags(text)
            
            # Chunk and process
            chunks = self._chunk_text(text)
            processed_count = 0
            
            for idx, chunk in enumerate(chunks):
                if len(chunk.split()) < 20:
                    continue
                    
                try:
                    embedding = self._get_embedding(chunk)
                    chunk_id = hashlib.md5(f"{site_id}_file_{upload_id}_{idx}".encode()).hexdigest()
                    
                    self.supabase.table('snappi_chunks').insert({
                        'id': chunk_id,
                        'url': f"custom_file_{upload_id}",
                        'section': file_name,
                        'chunk_index': idx,
                        'text': chunk,
                        'embedding': embedding,
                        'title': file_name,
                        'meta_description': f"Content from: {file_name}",
                        'summary': summary_info.get('summary', ''),
                        'tags': summary_info.get('tags', []),
                        'site_id': site_id,
                        'lang': 'en',
                        'scraped_ok': True,
                        'page_hash': hashlib.md5(text.encode()).hexdigest(),
                        'created_at': datetime.utcnow().isoformat()
                    }).execute()
                    
                    processed_count += 1
                    
                except Exception as e:
                    logger.error(f"Error processing chunk {idx}: {e}")
                    continue
            
            return {
                'success': True,
                'chunks_processed': processed_count,
                'total_chunks': len(chunks)
            }
            
        except Exception as e:
            logger.error(f"Error processing file: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _chunk_text(self, text: str) -> List[str]:
        """Split text into overlapping chunks"""
        words = text.split()
        chunks = []
        step = self.chunk_size - self.chunk_overlap
        
        for i in range(0, len(words), step):
            chunk = words[i:i + self.chunk_size]
            if chunk:
                chunks.append(" ".join(chunk))
                
        return chunks
    
    def _get_embedding(self, text: str, retries: int = 3) -> List[float]:
        """Get embedding from OpenAI with retry logic"""
        for attempt in range(retries):
            try:
                response = openai.embeddings.create(
                    model="text-embedding-3-large",
                    input=text
                )
                return response.data[0].embedding
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise
    
    def _get_summary_and_tags(self, text: str) -> Dict:
        """Generate summary and tags using GPT"""
        try:
            prompt = f"""You are a content analyzer. Given text content, generate:
- "summary": a 2-3 sentence summary
- "tags": 5-10 relevant topic tags

Content (first 10000 chars):
{text[:10000]}

Respond in JSON format only."""
            
            response = openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
            )
            
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")
            return {"summary": "", "tags": []}
    
    def _extract_pdf_text(self, file_data: bytes) -> str:
        """Extract text from PDF"""
        import io
        text = ""
        pdf_file = io.BytesIO(file_data)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
            
        return text.strip()
    
    def _extract_doc_text(self, file_data: bytes) -> str:
        """Extract text from DOC/DOCX"""
        import io
        doc_file = io.BytesIO(file_data)
        doc = docx.Document(doc_file)
        
        text = ""
        for paragraph in doc.paragraphs:
            text += paragraph.text + "\n"
            
        return text.strip()