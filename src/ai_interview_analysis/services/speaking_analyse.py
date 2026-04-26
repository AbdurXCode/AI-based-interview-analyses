# ============ start changes here

# ============= Start to Remove Print Condition ====================


import librosa
import numpy as np
# import tensorflow as tf
from pydub import AudioSegment
from keras.models import load_model
import os
from nltk.tokenize import word_tokenize
import matplotlib.pyplot as plt
import moviepy.editor as mp
import speech_recognition as sr
import nltk
from pydub.silence import split_on_silence
from pydub import AudioSegment

from speechmatics.models import ConnectionSettings
from speechmatics.batch_client import BatchClient
from httpx import HTTPStatusError


# Extract audio from video
def extract_audio_from_video(video_path, audio_output_path):
    try:
        video = mp.VideoFileClip(video_path)
        audio = video.audio
        if audio:
            audio.write_audiofile(audio_output_path)
        # print("Audio extraction successful!")
    except FileNotFoundError:
        print(f"Error: File not found. Check your video path: {video_path}")
    except Exception as e:
        print(f"Error: {e}")

# split path
def split_path(audio_path):
    common_dir, file_name = os.path.split(audio_path)
    return common_dir, file_name

# ======  Transcribe Speach and Count FillerWords/Interjections =========

# def recognize_speech(audio_path):
#     recognizer = sr.Recognizer()

#     with sr.AudioFile(audio_path) as source:
#         # print("Processing audio...")
#         recognizer.adjust_for_ambient_noise(source)
#         audio = recognizer.record(source)
#     try:
#         text = recognizer.recognize_google(audio)
#         return text
#     except sr.UnknownValueError:
#         print("Speech recognition could not understand audio")
#         return None
#     except sr.RequestError as e:
#         print(f"Could not request results from Google Speech Recognition service; {e}")
#         return None





def speech_recognize(api_key, file_path, language="en"):
    """
    Transcribe speech from an audio file using Speechmatics API.

    Args:
        api_key (str): Speechmatics API key.
        file_path (str): Path to the audio file for transcription.
        language (str): Language of the audio file (default is "en").

    Returns:
        str: Transcribed text.
    """
    settings = ConnectionSettings(
        url="https://asr.api.speechmatics.com/v2",
        auth_token=api_key,
    )

    # Define transcription parameters
    conf = {
        "type": "transcription",
        "transcription_config": {
            "language": language
        }
    }

    # Open the client using a context manager
    with BatchClient(settings) as client:
        try:
            job_id = client.submit_job(
                audio=file_path,
                transcription_config=conf,
            )
            print(f'Job {job_id} submitted successfully, waiting for transcript')

            # Note that in production, you should set up notifications instead of polling.
            # Notifications are described here: https://docs.speechmatics.com/features-other/notifications
            transcript = client.wait_for_completion(job_id, transcription_format='txt')
            # To see the full output, try setting transcription_format='json-v2'.
            return transcript
        except HTTPStatusError as e:
            if e.response.status_code == 401:
                return 'Invalid API key - Check your API_KEY at the top of the code!'
            elif e.response.status_code == 400:
                return e.response.json()['detail']
            else:
                raise e
            
            
            

#  Count Filler/Interjection

def count_interjection_features(text):
    words = word_tokenize(text.lower())
    # Count Interjections
    count_Interjection = len([word for word in words if word in ['um', 'uh', 'hmm','like','basically','well']])

    # Calculate the total number of words
    total_words = len(words)

    # Calculate the percentage of interjections
    interjection_percentage = (count_Interjection / total_words) * 100 if total_words > 0 else 0

    return interjection_percentage

# ===============  Detect Prolongation and repetation (Using Built-in Model)  ===============

def detect_prolongation(mfcc):

    model_pro = load_model('./models/pretrained_models/best_model_pro.h5')
    s = 0
    for m in mfcc:
        y = model_pro.predict(m.reshape(1,2,44,1), batch_size=1)
        y = np.around(y,decimals=2)
        if y[0][0] > 0.5:
            s += y[0][0]
    p_sev = s/len(mfcc)*100
    return p_sev

def detect_repetition(mfcc):
    model_rep = load_model('./models/pretrained_models/best_model_rep.h5') 
    s = 0
    for m in mfcc:
        y = model_rep.predict(m.reshape(1,13,44,1), batch_size=1)
        y = np.around(y,decimals=2)
        if y[0][0] > 0.9:
            s += y[0][0]
    r_sev = s/len(mfcc)*100
    return r_sev


#======================== Detect Stuttering (also include Pause)
def detect_stutter(audio):
    sound_file = AudioSegment.from_wav(audio)

    # ===================== Pauses Section
    chunks_for_pauses = split_on_silence(sound_file, silence_thresh=-40)  # Adjust silence threshold as needed
    total_segment = len(chunks_for_pauses)
    # Get the duration of each pause
    # pause_durations = [len(chunk) for chunk in chunks_for_pauses]

    # Calculate total duration of audio in seconds
    # total_duration = sum(pause_durations) / 1000

    # Calculate the percentage of pauses
    # pause_percentage = (sum(pause_durations) / total_duration) * 100 if total_duration > 0 else 0

    # ======================
    audio_chunks = sound_file[::1000]
    ps = 0
    rs = 0
    mfcc_arr_p = []
    mfcc_arr_r = []
    prolongation_file_paths = []
    repetition_file_paths = []

    # NOTES:
    # Create the 'chunks_test' directory if it doesn't exist
    # 'chunks_test' folder contaisns clips of audio
    # 'chunks_test' will create into current directory

    if not os.path.exists('chunks_test'):
        os.makedirs('chunks_test')

    for i, chunk in enumerate(audio_chunks):
        chunkfile = "chunks_test/chunk{0}.wav".format(i)
        chunk.export(chunkfile, format="wav")
        y, sr = librosa.load(chunkfile)
        mfcc = np.array(librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13))

        if mfcc.shape[0] == 13 and mfcc.shape[1] == 44:
            a = []
            a.append(mfcc)
            mfcc_arr_r.append(a)
            b = []
            b.append(mfcc[0])
            b.append(mfcc[12])
            mfcc_arr_p.append(b)

            # Detect prolongation and repetition using your models (model_pro and model_rep)
            p_sev_1 = detect_prolongation(np.array([b]))
            r_sev_1 = detect_repetition(np.array([a]))

            if p_sev_1 > 0.5:  # Set a threshold as needed
                prolongation_file_paths.append(chunkfile)

            if r_sev_1 > 0.5:  # Set a threshold as needed
                repetition_file_paths.append(chunkfile)

    mfcc_arr_r = np.array(mfcc_arr_r)
    mfcc_arr_p = np.array(mfcc_arr_p)

    mfcc_arr_r.reshape(mfcc_arr_r.shape[0], 13, 44, 1)
    mfcc_arr_p.reshape(mfcc_arr_p.shape[0], 2, 44, 1)

    p_sev = detect_prolongation(mfcc_arr_p)
    r_sev = detect_repetition(mfcc_arr_r)

    return p_sev, r_sev,prolongation_file_paths, repetition_file_paths,total_segment
