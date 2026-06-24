from google.cloud import storage
from django.conf import settings
import os
from datetime import timedelta
import mimetypes

class GCSHelper:
    def __init__(self):
        """
        Initialize GCS client. If credentials are not available (local development),
        set client to None and operations will be handled gracefully.
        """
        try:
            self.client = storage.Client()
            self.bucket_name = settings.GCS_BUCKET_NAME
            self.bucket = self.client.bucket(self.bucket_name)
            self.is_available = True
        except Exception as e:
            self.client = None
            self.bucket = None
            self.bucket_name = getattr(settings, 'GCS_BUCKET_NAME', None)
            self.is_available = False
    
    def _check_availability(self):
        """Check if GCS is available, raise error if not."""
        if not self.is_available:
            raise Exception("GCS is not available. Please configure GCS credentials for production use.")
    
    def upload_file(self, file_obj, destination_path, content_type=None):
        """
        Upload a file to GCS bucket.
        
        Args:
            file_obj: File object or file path
            destination_path: Path in bucket (e.g., 'projects/123/template.xlsx')
            content_type: MIME type of the file
        
        Returns:
            dict: {'url': public_url, 'blob_name': blob_name}
        """
        self._check_availability()
        
        try:
            blob = self.bucket.blob(destination_path)
            
            # Determine content type if not provided
            if not content_type:
                content_type, _ = mimetypes.guess_type(destination_path)
                if not content_type:
                    content_type = 'application/octet-stream'
            
            # Upload the file
            if isinstance(file_obj, str):
                # If file_obj is a path string
                blob.upload_from_filename(file_obj, content_type=content_type)
            else:
                # If file_obj is a file object
                file_obj.seek(0)  # Reset file pointer to beginning
                blob.upload_from_file(file_obj, content_type=content_type)
            
            # Make the blob publicly accessible (optional)
            # blob.make_public()
            
            return {
                'url': f'gs://{self.bucket_name}/{destination_path}',
                'public_url': blob.public_url,
                'blob_name': destination_path
            }
        except Exception as e:
            raise Exception(f"Failed to upload file to GCS: {str(e)}")
    
    def generate_signed_url(self, blob_name, expiration=3600):
        """
        Generate a signed URL for private access to a blob.
        
        Args:
            blob_name: Name of the blob in bucket
            expiration: URL expiration time in seconds (default 1 hour)
        
        Returns:
            str: Signed URL
        """
        self._check_availability()
        
        try:
            blob = self.bucket.blob(blob_name)
            url = blob.generate_signed_url(
                version="v4",
                expiration=timedelta(seconds=expiration),
                method="GET"
            )
            return url
        except Exception as e:
            raise Exception(f"Failed to generate signed URL: {str(e)}")
    
    def delete_file(self, blob_name):
        """
        Delete a file from GCS bucket.
        
        Args:
            blob_name: Name of the blob to delete
        
        Returns:
            bool: True if successful
        """
        self._check_availability()
        
        try:
            blob = self.bucket.blob(blob_name)
            blob.delete()
            return True
        except Exception as e:
            raise Exception(f"Failed to delete file from GCS: {str(e)}")
    
    def file_exists(self, blob_name):
        """
        Check if a file exists in the bucket.
        
        Args:
            blob_name: Name of the blob
        
        Returns:
            bool: True if exists
        """
        if not self.is_available:
            return False
        
        blob = self.bucket.blob(blob_name)
        return blob.exists()

# Create a singleton instance
gcs_helper = GCSHelper()
