# ============= Start to Remove Print Condition ====================


from speeking_skills_analyse import extract_audio_from_video,count_interjection_features,split_path,detect_stutter,speech_recognize #,recognize_speech,

import os
from keras.models import load_model
import nltk
import matplotlib.pyplot as plt
import nltk
import os

# nltk.download('punkt')
# nltk.download('stopwords')


def speaking_skills_analysis_module(video_path):
        
    # ===============================================

    # Check if NLTK data directory exists
    nltk_data_dir = os.path.join(os.path.expanduser("~"), "nltk_data")
    if not os.path.exists(nltk_data_dir):
        # If directory does not exist, download NLTK data
        nltk.download('punkt', download_dir=nltk_data_dir)
        nltk.download('stopwords', download_dir=nltk_data_dir)

    # Now nltk_data_dir contains the NLTK data
    # You can use it to set NLTK data path if needed
    nltk.data.path.append(nltk_data_dir)

    # Now you can proceed with your script

    # =================== Path Setting ============================

    # video_path = "./assets/Personal_Stutter_Sample.mp4"
    # which will be the audio output path with name of file
    audio_output_path = "./assets/Personal_Stutter_Sample.wav"
    
    # =================================================================
    
    # Extract audio from video
    extract_audio_from_video(video_path, audio_output_path)

    # Recognize speech from the extracted audio
    
    
    # Example usage:
    API_KEY = 'tWwevO92tzXDwSC7v6DonkuBJzE7a56L'    # "1JFKtmqTEy9HpA6s2Eg989CAcNW9aKpV"
    PATH_TO_FILE = audio_output_path#"./assets/Personal_Stutter_Sample.wav"
    spoken_text = speech_recognize(API_KEY, PATH_TO_FILE)
    print(spoken_text)
    
    
    # spoken_text = recognize_speech(audio_output_path)
    # print(f"spoken_text : {spoken_text}")

    # filler/Interjections words
    fillerWord_percentage = count_interjection_features(spoken_text)
    # print(f"Interjection Words:{fillerWord_percentage}")

    # directory
    common_dir, file_name = split_path(audio_output_path)

    common_dir = common_dir  #'/content/gdrive/MyDrive/Video Analyse Project'
    file_name = file_name    #'Personal_Stuttering_converted.wav'

    file_path = os.path.join(common_dir, file_name)

    if os.path.isfile(file_path) and file_name.endswith('.wav'):
        # print('\n' + file_name)

        # detect stutter calling
        p_sev, r_sev ,prolongation_path,repetition_path, pauses_percentage = detect_stutter(file_path)
        o_sev = (p_sev+r_sev+pauses_percentage+fillerWord_percentage)/4
        
            
        # print("\nHere is the stuttering details:\n")

        # print(f'Prolongation %       : {p_sev:.2f}')
        # print(f'Repetition %         : {r_sev:.2f}')
        # print(f"Interjection Words % : {fillerWord_percentage:.2f}")
        # print(f"Pauses/Blocks %      : {pauses_percentage:.2f}")
        # print(f'Overall stutter %    : {o_sev:.2f}')

        # print("\nStuttering Graph as follow:\n")

        # # Categories
        # categories = ['Prolongation', 'Repetition', 'Interjections', 'Pauses', 'Overall Stutter']

        # # Values
        # values = [p_sev, r_sev, fillerWord_percentage, pauses_percentage, o_sev]

        # # Plotting
        # plt.bar(categories, values, color=['blue', 'orange', 'green', 'black', 'grey'])
        # plt.ylim(0, 100)  # Set y-axis limit to 0-100% for percentage values
        # plt.title('Stuttering Analysis Results')
        # plt.xlabel('Stuttering Type')
        # plt.ylabel('Percentage')


        # # Displaying percentage values on top of each bar
        # for i, value in enumerate(values):
        #     plt.text(i, value + 1, f'{value:.2f}%', ha='center', va='bottom')

        # plt.show()

    else:
        print(f"Invalid file: {file_name}")
    

    speak_analysis_dictionary = dict()
    speak_analysis_dictionary['spoken_text']        = spoken_text
    speak_analysis_dictionary['Prolongation']       = round(p_sev, 2)
    speak_analysis_dictionary['Repetition']         = round(r_sev, 2)
    speak_analysis_dictionary['Interjection_Words'] = round(fillerWord_percentage, 2)
    speak_analysis_dictionary['Pauses_Blocks']      = round(pauses_percentage, 2)
    speak_analysis_dictionary['Overall_Stutter']    = round(o_sev, 2)

    
    return speak_analysis_dictionary
    




