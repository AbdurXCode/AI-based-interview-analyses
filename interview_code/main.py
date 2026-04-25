
# from Driver_Gaze import track_gaze_module
# from driver_speeking_skills_analysis import speaking_skills_analysis_module
# from driver_body_language_analysis import body_language_analysis_module

# # gaze_path = "./assets/GazeMovement_TestingVideo.mp4"

# def head_driver():

#     #  Gaze Tracking module
#     print("-------------------- Gaze Tracking Module started ---------------------")
#     gaze_track_dict = track_gaze_module("./assets/GazeMovement_TestingVideo.mp4")

#     # Speaking Skill Analysis Module
#     print("-------------------- Speaking skills started ---------------------")
#     speaking_analyse_dict = speaking_skills_analysis_module("./assets/Personal_Stutter_Sample.mp4")

#     # Body language Module
#     print("-------------------- Body Language started ---------------------")
#     body_analyse_dict = body_language_analysis_module("./assets/Body_language_sampleVideo.mp4")

#     video_analyse_dictionary = {
#         "gaze_track": gaze_track_dict,
#         "speaking_analysis": speaking_analyse_dict,
#         "body_analysis": body_analyse_dict
#     }
    
#     return video_analyse_dictionary

# if __name__ == "__main__":
#     video_analysis_result = head_driver()
#     print(video_analysis_result)

# =====================================================     Fast API Implementation using hardcoded PATH =============================



# from fastapi import FastAPI
# from Driver_Gaze import track_gaze_module
# from driver_speeking_skills_analysis import speaking_skills_analysis_module
# from driver_body_language_analysis import body_language_analysis_module

# app = FastAPI()

# @app.get("/Interview-Assessment")
# def head_driver():
    
#     # Gaze Tracking module
#     print("-------------------- Gaze Tracking Module..... ---------------------")
#     gaze_track_dict = track_gaze_module("./assets/GazeMovement_TestingVideo.mp4")

#     # Speaking Skill Analysis Module
#     print("-------------------- Speaking Skill Analysis Completed...... ---------------------")
#     speaking_analyse_dict = speaking_skills_analysis_module("./assets/Personal_Stutter_Sample.mp4")

#     # Body language Module
#     print("-------------------- Body Language Analysis Completed..... ---------------------")
#     body_analyse_dict = body_language_analysis_module("./assets/Body_language_sampleVideo.mp4")

#     video_analyse_dictionary = {
#         "gaze_track": gaze_track_dict,
#         "speaking_analysis": speaking_analyse_dict,
#         "body_analysis": body_analyse_dict
#     }
    
#     return video_analyse_dictionary

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="127.0.0.1", port=8000)



# ==================================  Fast API Implementation using File upload system ==============================


# from Driver_Gaze import track_gaze_module
# from driver_speeking_skills_analysis import speaking_skills_analysis_module
# from driver_body_language_analysis import body_language_analysis_module

# from fastapi import FastAPI, File, UploadFile

# app = FastAPI()


# def head_driver(video_file):
#     # Save the uploaded file to a temporary location
#     with open("temp_video.mp4", "wb") as buffer:
#         buffer.write(video_file)

#     # Gaze Tracking module
#     print("-------------------- Gaze Tracking Module..... ---------------------")
#     gaze_track_dict = track_gaze_module("temp_video.mp4")

#     # Speaking Skill Analysis Module
#     print("-------------------- Speaking Skill Analysis Completed...... ---------------------")
#     speaking_analyse_dict = speaking_skills_analysis_module("temp_video.mp4")

#     # Body language Module
#     print("-------------------- Body Language Analysis Completed..... ---------------------")
#     body_analyse_dict = body_language_analysis_module("temp_video.mp4")

#     video_analyse_dictionary = {
#         "gaze_track": gaze_track_dict,
#         "speaking_analysis": speaking_analyse_dict,
#         "body_analysis": body_analyse_dict
#     }

#     return video_analyse_dictionary

# @app.post("/analyze_video/")
# async def analyze_video(video_file: UploadFile = File(...)):
#     video_analysis_result = head_driver(await video_file.read())
#     return video_analysis_result

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="127.0.0.1", port=8000)


# =============================== API with Accepting videos and cores =================================

# from fastapi import FastAPI, UploadFile, File
# from fastapi.middleware.cors import CORSMiddleware
# from typing import Dict
# from Driver_Gaze import track_gaze_module
# from driver_speeking_skills_analysis import speaking_skills_analysis_module
# from driver_body_language_analysis import body_language_analysis_module

# app = FastAPI()

# # Enable CORS for all origins
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["GET", "POST", "OPTIONS"],
#     allow_headers=["*"],
# )

# @app.post("/Interview-Assessment")
# async def head_driver(video_file: UploadFile = File(...)):
    
#     # Save the uploaded file locally
#     with open(f"./assets/{video_file.filename}", "wb") as f:
#         f.write(video_file.file.read())
    
#     # Gaze Tracking module
#     print("-------------------- Gaze Tracking Module..... ---------------------")
#     gaze_track_dict = track_gaze_module(f"./assets/{video_file.filename}")

#     # Speaking Skill Analysis Module
#     print("-------------------- Speaking Skill Analysis Completed...... ---------------------")
#     speaking_analyse_dict = speaking_skills_analysis_module(f"./assets/{video_file.filename}")

#     # Body language Module
#     print("-------------------- Body Language Analysis Completed..... ---------------------")
#     body_analyse_dict = body_language_analysis_module(f"./assets/{video_file.filename}")

#     video_analyse_dictionary = {
#         "gaze_track": gaze_track_dict,
#         "speaking_analysis": speaking_analyse_dict,
#         "body_analysis": body_analyse_dict
#     }
    
#     return video_analyse_dictionary


# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, port=8000)
    
    
    
# ===========================================    check Handles + API with Accepting videos and cores ==================================

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict
from Driver_Gaze import track_gaze_module
import os 
import shutil
from driver_speeking_skills_analysis import speaking_skills_analysis_module
from driver_body_language_analysis import body_language_analysis_module
from datetime import datetime
from typing import List



app = FastAPI()

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv'}

# @app.post("/Interview-Assessment")
# async def head_driver(video_file: UploadFile = File(...)):
#     # Check if the uploaded file is a video file
#     if not video_file.filename.split('.')[-1] in ALLOWED_VIDEO_EXTENSIONS:
#         return {"error": "Only video files are allowed."}

#     # Save the uploaded file locally
#     with open(f"./assets/{video_file.filename}", "wb") as f:
#         f.write(video_file.file.read())
    
#     # Gaze Tracking module
#     print("-------------------- Gaze Tracking Module..... ---------------------")
#     gaze_track_dict = track_gaze_module(f"./assets/{video_file.filename}")

#     # Speaking Skill Analysis Module
#     print("-------------------- Speaking Skill Analysis Completed...... ---------------------")
#     speaking_analyse_dict = speaking_skills_analysis_module(f"./assets/{video_file.filename}")

#     # Body language Module
#     print("-------------------- Body Language Analysis Completed..... ---------------------")
#     body_analyse_dict = body_language_analysis_module(f"./assets/{video_file.filename}")

#     video_analyse_dictionary = {
#         "gaze_track": gaze_track_dict,
#         "speaking_analysis": speaking_analyse_dict,
#         "body_analysis": body_analyse_dict
#     }
    
#     # Delete unnecessary files and directories ....
#     folder_path = "./assets"
#     directory_path = "./chunks_test"
    
#     files_to_delete = [os.path.join(folder_path, filename) for filename in os.listdir(folder_path) if not filename.endswith('.csv')]
#     for file_path in files_to_delete:
#         os.remove(file_path)
#     print("Non-CSV files deleted successfully.")
#     # Delete the entire directory and its contents
#     shutil.rmtree(directory_path)
    
#     return video_analyse_dictionary






# ==================================================================================

ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv','webm'}

@app.post("/Interview-Assessment")
async def head_driver(video_files: List[UploadFile] = File(...)):
    video_analyse_dictionary = {}
    
    for video_file in video_files:
        # Check if the uploaded file is a video file
        if not video_file.filename.split('.')[-1] in ALLOWED_VIDEO_EXTENSIONS:
            return {"error": "Only video files are allowed."}

        # Save the uploaded file locally
        with open(f"./assets/{video_file.filename}", "wb") as f:
            f.write(video_file.file.read())

        # Close the file handle after writing
        video_file.file.close()

        # Gaze Tracking module
        print("-------------------- Gaze Tracking start..... ---------------------")
        gaze_track_dict = track_gaze_module(f"./assets/{video_file.filename}")
        print("-------------------- Gaze Tracking completed..... ---------------------")
        

        # Speaking Skill Analysis Module
        print("-------------------- Speaking Skill Analysis start...... ---------------------")
        speaking_analyse_dict = speaking_skills_analysis_module(f"./assets/{video_file.filename}")
        print("-------------------- Speaking Skill Analysis Completed...... ---------------------")


        # Body language Module
        print("-------------------- Body Language Analysis start..... ---------------------")
        body_analyse_dict = body_language_analysis_module(f"./assets/{video_file.filename}")
        print("-------------------- Body Language Analysis completed..... ---------------------")


        video_analyse_dictionary[video_file.filename] = {
            "gaze_track": gaze_track_dict,
            "speaking_analysis": speaking_analyse_dict,
            "body_analysis": body_analyse_dict
        }

        print("-------------------- Start to delete unnecessary Files..... ---------------------")
        
        
        # Delete unnecessary files and directories
        folder_path = "./assets"
        directory_path = "./chunks_test"
        
        files_to_delete = [os.path.join(folder_path, filename) for filename in os.listdir(folder_path) if not filename.endswith('.csv')]
        for file_path in files_to_delete:
            try:
                os.remove(file_path)
                print(f"{file_path} deleted successfully.")
            except PermissionError:
                print(f"Permission error: {file_path}")

        # Delete the entire directory and its contents
        shutil.rmtree(directory_path)

        print("-------------------- Uncessary files are deleted successfully ..... ---------------------")

        print("=============================    API Run Successfuly ========================")
    return video_analyse_dictionary


# ===================================================================================









if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=8080)
    
