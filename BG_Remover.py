# import cv2
# import numpy as np

# def remove_background(image):
#     # Convert image to grayscale
#     gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
#     # Use a threshold to segment the foreground (adaptive thresholding can be used for better results)
#     _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)
    
#     # Morphological operations to remove noise
#     kernel = np.ones((3,3), np.uint8)
#     opening = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=2)
    
#     # Dilate the foreground region to ensure it covers the entire object
#     sure_bg = cv2.dilate(opening, kernel, iterations=3)
    
#     return sure_bg

# def replace_background(foreground, background, mask):
#     # Invert the mask to get the foreground region
#     mask_inv = cv2.bitwise_not(mask)
    
#     # Extract the foreground from the original image
#     foreground_no_bg = cv2.bitwise_and(foreground, foreground, mask=mask_inv)
    
#     # Extract the background from the background image
#     background_no_fg = cv2.bitwise_and(background, background, mask=mask)
    
#     # Combine the foreground and background images
#     result = cv2.add(foreground_no_bg, background_no_fg)
    
#     return result

# # Load the images
# foreground_image = cv2.imread('./assets/Image.jpeg')
# background_image = cv2.imread('./assets/Background.jpeg')

# # Resize background image to match foreground image size
# background_image_resized = cv2.resize(background_image, (foreground_image.shape[1], foreground_image.shape[0]))

# # Remove background from the foreground image
# foreground_mask = remove_background(foreground_image)

# # Replace background
# result_image = replace_background(foreground_image, background_image_resized, foreground_mask)

# # Display the result
# cv2.imshow('Result', result_image)
# cv2.waitKey(0)
# cv2.destroyAllWindows()



# =================================  BG Remover 2 =========================================

# from rembg import remove
# from PIL import Image



# img = Image.open('./assets/Einstaien.png')
# removeBG = remove(img)
# removeBG.save("./assets/Einstaien.png")

# ===============================  BG remover 3 ===================================


from rembg import remove
from PIL import Image
from PIL import ImageFilter

def paste_foreground_on_background(input_image_path, output_image_path, background_image_path, blur_radius=2):
    """
    Removes the background of an image using Rembg, smooths edges, pastes the foreground
    (extracted object) onto a new background image, and resizes it to fit.

    Args:
        input_image_path (str): Path to the input image.
        output_image_path (str): Path to save the output image.
        background_image_path (str): Path to the background image.
        blur_radius (int, optional): Radius for edge smoothing (default: 2).
    """

    # Remove background using Rembg
    input_image = Image.open(input_image_path)
    foreground_with_alpha = remove(input_image)  # Output with alpha channel (transparency)

    # Smooth foreground edges with Gaussian blur
    # foreground_with_alpha = foreground_with_alpha.filter(ImageFilter.GaussianBlur(blur_radius))

    # Open the new background image
    background_image = Image.open(background_image_path)

    # Resize foreground to fit background dimensions while maintaining aspect ratio
    foreground_width, foreground_height = foreground_with_alpha.size
    background_width, background_height = background_image.size

    # Calculate resize ratio to fit within background while preserving aspect ratio
    scale = min(background_width / foreground_width, background_height / foreground_height)
    new_foreground_width = int(foreground_width * scale)
    new_foreground_height = int(foreground_height * scale)

    # Resize foreground image
    foreground_with_alpha = foreground_with_alpha.resize((new_foreground_width, new_foreground_height),  Image.Resampling.LANCZOS)

    # Calculate position to center foreground on background
    x_offset = (background_width - new_foreground_width) // 2
    y_offset = (background_height - new_foreground_height) // 2

    # Paste the foreground image (with alpha) onto the background
    background_image.paste(foreground_with_alpha, (x_offset, y_offset), mask=foreground_with_alpha)

    # Save the final image with the foreground on the new background
    background_image.save(output_image_path)


# C:/Users/Delll/Downloads/AI_Interview_Analysis/assets/actor.jpg
input_image_path = "C:/Users/Delll/Downloads/imagesample/image 3.jpg" 
background_image_path = './assets/backgrounds/bg4.jpg'

output_image_path = './assets/output_8.png'  # Use PNG to preserve transparency

blur_radius = 2  # Adjust for desired edge smoothing

paste_foreground_on_background(input_image_path, output_image_path, background_image_path, blur_radius)

print('Image with smoothed foreground on new background saved to:', output_image_path)
