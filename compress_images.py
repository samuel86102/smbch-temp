import os
from PIL import Image

TARGET_SIZE_KB = 1024
TARGET_SIZE_BYTES = TARGET_SIZE_KB * 1024

def compress_image(image_path, target_size=TARGET_SIZE_BYTES):
    """Compress image to target size, starting from current quality."""
    img = Image.open(image_path)
    if img.mode == 'RGBA':
        img = img.convert('RGB')
    
    quality = 95
    step = 5
    
    while quality >= 20:
        img.save(image_path, 'JPEG', quality=quality, optimize=True)
        if os.path.getsize(image_path) <= target_size:
            return True
        quality -= step
    
    return False

def main():
    tour_dir = 'image/tour'
    
    for root, dirs, files in os.walk(tour_dir):
        for filename in files:
            if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                filepath = os.path.join(root, filename)
                current_size = os.path.getsize(filepath)
                
                if current_size > TARGET_SIZE_BYTES:
                    print(f'Compressing: {filepath} ({current_size // 1024} KB)')
                    compress_image(filepath)
                    new_size = os.path.getsize(filepath)
                    print(f'  -> {new_size // 1024} KB')
                else:
                    print(f'Skip (already small): {filepath} ({current_size // 1024} KB)')

if __name__ == '__main__':
    main()
