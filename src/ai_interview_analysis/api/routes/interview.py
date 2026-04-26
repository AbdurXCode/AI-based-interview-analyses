from fastapi import APIRouter, File, UploadFile

from ai_interview_analysis.services.gaze_driver import track_gaze_module
from ai_interview_analysis.services.speaking_driver import speaking_skills_analysis_module
from ai_interview_analysis.services.body_language_driver import body_language_analysis_module

import os
import shutil


router = APIRouter()

ALLOWED_VIDEO_EXTENSIONS = {"mp4", "avi", "mov", "wmv", "flv", "mkv", "webm"}


@router.post("/Interview-Assessment")
async def interview_assessment(
    video_file: UploadFile = File(
        ...,
        description="Upload an interview video (.mp4, .webm, etc.). For multiple videos, call this endpoint multiple times or use curl with repeated form fields.",
    ),
):
    video_analyse_dictionary = {}

    os.makedirs("./assets", exist_ok=True)

    ext = video_file.filename.split(".")[-1].lower() if video_file.filename else ""
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        return {"error": "Only video files are allowed."}

    target_path = f"./assets/{video_file.filename}"
    with open(target_path, "wb") as f:
        f.write(video_file.file.read())
    video_file.file.close()

    gaze_track_dict = track_gaze_module(target_path)
    speaking_analyse_dict = speaking_skills_analysis_module(target_path)
    body_analyse_dict = body_language_analysis_module(target_path)

    video_analyse_dictionary[video_file.filename] = {
        "gaze_track": gaze_track_dict,
        "speaking_analysis": speaking_analyse_dict,
        "body_analysis": body_analyse_dict,
    }

    # Best-effort cleanup (matches original behavior)
    folder_path = "./assets"
    directory_path = "./chunks_test"
    files_to_delete = [
        os.path.join(folder_path, filename)
        for filename in os.listdir(folder_path)
        if not filename.endswith(".csv")
    ]
    for file_path in files_to_delete:
        try:
            os.remove(file_path)
        except PermissionError:
            pass
        except FileNotFoundError:
            pass

    try:
        shutil.rmtree(directory_path)
    except FileNotFoundError:
        pass

    return video_analyse_dictionary

