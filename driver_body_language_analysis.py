
from body_language_analysis import findDistance, calculate_angle
import mediapipe as mp # Import mediapipe
import cv2 # Import opencv
import pandas as pd
import pickle
import matplotlib.pyplot as plt
from collections import Counter
import numpy as np
import csv
import os
from joblib import load

def body_language_analysis_module(InputVideoPath):

    directory_path = "./pretrained_models"
    model_name = "body_language.pkl"

    file_path = os.path.join(directory_path, model_name)

    # model = load('./pretrained_models/body_language.pkl')
    
    with open(file_path, 'rb') as f:
        model = pickle.load(f)

    mp_drawing = mp.solutions.drawing_utils # Drawing helpers
    mp_holistic = mp.solutions.holistic # Mediapipe Solutions

    cap = cv2.VideoCapture(InputVideoPath)

    cap = cap
    # Initiate holistic model

    counter = 0
    slump_counter = 0
    leaning_backword_counter = 0
    clunch_counter = 0
    stage = None
    agressive_counter = 0
    shrugiing_counter = 0
    touchFace_counter = 0
    global isFaceFound
    isFaceFound = False
    status ='Slump'
  

    with mp_holistic.Holistic(min_detection_confidence=0.5, min_tracking_confidence=0.5) as holistic:

        while cap.isOpened():
            ret, frame = cap.read()

            if not ret:
                print("End of video")
                break

            h,w = frame.shape[:2]
            # Recolor Feed
            image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image.flags.writeable = False

            # Make Detections
            results = holistic.process(image)

            # Recolor image back to BGR for rendering
            image.flags.writeable = True
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

            # >>>>>>>>>>>>>>>>>-----------  Draw Landmarks------------>>>>>>>>>>>>>>>>>
            # Check if face landmarks are visible with visibility > 0.2
            
            if results.face_landmarks and any(landmark.visibility > 0.2 for landmark in results.face_landmarks.landmark):
                # 1. Draw face landmarks
                mp_drawing.draw_landmarks(image, results.face_landmarks, mp_holistic.FACEMESH_TESSELATION,
                                        mp_drawing.DrawingSpec(color=(80,110,10), thickness=1, circle_radius=1),
                                        mp_drawing.DrawingSpec(color=(80,256,121), thickness=1, circle_radius=1)
                                        )
                isFaceFound = True
            else:
                print("face is missing")
                isFaceFound = False

            # 2. Right hand
            mp_drawing.draw_landmarks(image, results.right_hand_landmarks, mp_holistic.HAND_CONNECTIONS,
                                    mp_drawing.DrawingSpec(color=(80,22,10), thickness=2, circle_radius=4),
                                    mp_drawing.DrawingSpec(color=(80,44,121), thickness=2, circle_radius=2)
                                    )

            # 3. Left Hand
            mp_drawing.draw_landmarks(image, results.left_hand_landmarks, mp_holistic.HAND_CONNECTIONS,
                                    mp_drawing.DrawingSpec(color=(121,22,76), thickness=2, circle_radius=4),
                                    mp_drawing.DrawingSpec(color=(121,44,250), thickness=2, circle_radius=2)
                                    )

            # 4. Pose Detections
            mp_drawing.draw_landmarks(image, results.pose_landmarks, mp_holistic.POSE_CONNECTIONS,
                                    mp_drawing.DrawingSpec(color=(245,117,66), thickness=2, circle_radius=4),
                                    mp_drawing.DrawingSpec(color=(245,66,230), thickness=2, circle_radius=2)
                                    )
            


            # Export coordinates for motion analysis as natural or unhappy
            try:
                # Extract Pose landmarks
                pose = results.pose_landmarks.landmark
                pose_row = list(np.array([[landmark.x, landmark.y, landmark.z, landmark.visibility] for landmark in pose]).flatten())

                # Extract Face landmarks
                face = results.face_landmarks.landmark
                face_row = list(np.array([[landmark.x, landmark.y, landmark.z, landmark.visibility] for landmark in face]).flatten())

                # Export to CSV
                with open('./assets/coords_pred.csv', mode='a', newline='') as f:
                    csv_writer = csv.writer(f, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
                    csv_writer.writerow(face_row)
            except:
                pass


            # >>>>>>>>>>>>>>>>>-----------  Exctract Landmarks------------>>>>>>>>>>>>>>>>>

            # posture landmarks

            if results.pose_landmarks:

                shoulder   = [results.pose_landmarks.landmark[11].x, results.pose_landmarks.landmark[11].y]
                shoulder_R = [results.pose_landmarks.landmark[12].x, results.pose_landmarks.landmark[11].y]

                left_shoulder_y = results.pose_landmarks.landmark[11].y
                left_shoulder_z = results.pose_landmarks.landmark[11].z

                
                # print (f"=====================  Shoulder Distance =================\n Shoulder Distance = {shoulder_Dist}\n")

                elbow = [results.pose_landmarks.landmark[13].x, results.pose_landmarks.landmark[13].y]
                elbow_R = [results.pose_landmarks.landmark[14].x, results.pose_landmarks.landmark[14].y]

                wrist = [results.pose_landmarks.landmark[15].x, results.pose_landmarks.landmark[15].y]
                wrist_R = [results.pose_landmarks.landmark[16].x, results.pose_landmarks.landmark[16].y]

                left_knee_y = results.pose_landmarks.landmark[25].y
                left_knee_z = results.pose_landmarks.landmark[25].z

            else: 
                shoulder = [0,0]
                shoulder_R = [0,0]
                left_shoulder_y = 0
                left_shoulder_z = 0
                elbow = [0,0]
                elbow_R = [0,0]
                wrist = [0,0]
                wrist_R = [0,0]
                left_knee_y = 0
                left_knee_z = 0

            if results.right_hand_landmarks:
                # Get the coordinates of the right wrist landmark at index 0
                index_tip_right = [results.right_hand_landmarks.landmark[8].x, results.right_hand_landmarks.landmark[8].y]
                index_pip_right = [results.right_hand_landmarks.landmark[6].x, results.right_hand_landmarks.landmark[6].y]
                index_mcp_right = [results.right_hand_landmarks.landmark[5].x, results.right_hand_landmarks.landmark[5].y]

                # for touch face
                index_fingure_right_x =  results.right_hand_landmarks.landmark[8].x
                index_fingure_right_y =  results.right_hand_landmarks.landmark[8].y

            else:
                # Assign default values if left hand landmarks are not detected
                index_tip_right = [0, 0]
                index_pip_right = [0, 0]
                index_mcp_right = [0, 0]
                index_fingure_right_x = 0
                index_fingure_right_y = 0

            # Check if the left wrist is open
            if results.left_hand_landmarks:

                # Get the coordinates of the left wrist landmark at index 0
                index_tip_left = [results.left_hand_landmarks.landmark[8].x, results.left_hand_landmarks.landmark[8].y]
                index_pip_left = [results.left_hand_landmarks.landmark[6].x, results.left_hand_landmarks.landmark[6].y]
                index_mcp_left = [results.left_hand_landmarks.landmark[5].x, results.left_hand_landmarks.landmark[5].y]

                # index_fingure_left_y =  results.right_hand_landmarks.landmark[8].x
                index_fingure_left_x =  results.left_hand_landmarks.landmark[8].x
                index_fingure_left_y =  results.left_hand_landmarks.landmark[8].y

            else:
                # Assign default values if left hand landmarks are not detected
                index_tip_left = [0, 0]
                index_pip_left = [0, 0]
                index_mcp_left = [0, 0]
                index_fingure_left_x = 0
                index_fingure_left_y = 0
            # >>>>>>>>>>>>>>>>>-----------  Calculate Angles ------------>>>>>>>>>>>>>>>>>

            # calculate agnle for shurugging
            if results.pose_landmarks:
            # Calculate distance between left shoulder and right shoulder points.
                shrug_dist_left = findDistance(results.pose_landmarks.landmark[11].x*w, results.pose_landmarks.landmark[11].y*h, results.pose_landmarks.landmark[7].x*w, results.pose_landmarks.landmark[7].y*h)
                angle_touchingFace_leftHand = findDistance(results.pose_landmarks.landmark[0].x*w, results.pose_landmarks.landmark[0].y*h, index_fingure_left_x*w,index_fingure_left_y*h)
                angle_touchingFace_rightHand = findDistance(results.pose_landmarks.landmark[0].x*w, results.pose_landmarks.landmark[0].y*h, index_fingure_right_x*w,index_fingure_right_y*h)

            else:
                shrug_dist_left = 0
                angle_touchingFace_leftHand = 0
                angle_touchingFace_rightHand = 0

            # Right
            aggressive_angle_right = calculate_angle(wrist_R,shoulder_R,shoulder)
            # Left
            aggressive_angle_left = calculate_angle(wrist,shoulder,shoulder_R)

            # Calculate angle for wild movement
            angle = calculate_angle(shoulder, elbow, wrist)
            angle_R = calculate_angle(shoulder_R, elbow_R, wrist_R)

            # Calculate angle for slumping leaning
            
            left_shoulder_knee_angle  = findDistance(left_shoulder_y*w,left_shoulder_z *h, left_knee_y*w, left_knee_z*h)

            # left hand's fingures
            angle_LeftIndexFingure = calculate_angle(index_tip_left, index_pip_left, index_mcp_left)
            angle_rightIndexFingure = calculate_angle(index_tip_right, index_pip_right, index_mcp_right)
            
            
            # >>>>>>>>>>>>>>>>>-----------  Logic Building ------------>>>>>>>>>>>>>>>>>

                #  logic for shrugging

            if  shrug_dist_left <= 80 or shrug_dist_left <=80:
                shrugiing_counter +=1

            # Logic for aggressiveness

            if aggressive_angle_right <= 20 or aggressive_angle_left <=20:
                agressive_counter += 1

            # LOGIC for clunching

            if  angle_LeftIndexFingure <=10 or angle_rightIndexFingure <=10:
                clunch_counter+=1

            # Logic for detect Hands Touching on Face

            if angle_touchingFace_rightHand <= 60 or angle_touchingFace_leftHand <= 60:
                touchFace_counter +=1

            # LOGIC Slump,Leaning

            if left_shoulder_knee_angle >= 400 and left_shoulder_knee_angle <= 500:
                status = 'notSlump'
            else:
                
                if left_shoulder_knee_angle > 500:
                    slump_counter +=1     

                elif left_shoulder_knee_angle < 400:
                    leaning_backword_counter +=1

            # LOGIC for Wild hand movements

            if angle > 160 or angle_R > 160:
                counter +=1
            if angle < 30 or angle_R < 30:
                counter +=1

            if cv2.waitKey(10) & 0xFF == ord('q'):
                break

    cap.release()
    cv2.destroyAllWindows()

    if isFaceFound:
        df = pd.read_csv('./assets/coords_pred.csv')
        Prediction_data = df
        yhat = model.predict(Prediction_data)

        # Assuming yhat is your array of predictions
        predictions_counter = Counter(yhat)

        # Count occurrences of "natural" and "unhappy/shocked"
        natural_count = predictions_counter["natural"]
        unhappy_shocked_count = predictions_counter["unhappy/shocked"]

        sumOfemotion = natural_count+unhappy_shocked_count
        percent_OfNaturalEmotion = (natural_count/sumOfemotion)*100
        percent_of_OfUnhappyEmotion = (unhappy_shocked_count/sumOfemotion)*100
    else:
        percent_OfNaturalEmotion = 0
        percent_of_OfUnhappyEmotion = 0


    wildMovement_bad_time =  (1 / 30) * counter
    slumpPse_bad_time =  (1 / 30) * slump_counter
    LeaningPose_bad_time =  (1 / 30) * leaning_backword_counter
    Clunching_bad_time =  (1 / 30) * clunch_counter
    AggressivePose_bad_time =  (1 / 30) * agressive_counter
    ShruggingPose_bad_time =  (1 / 30) * shrugiing_counter
    FaceTouch_bad_time =  (1 / 30) * touchFace_counter
    Confuse_duration = (1 / 30) * percent_of_OfUnhappyEmotion
    natural_emotion = (1 / 30) * percent_OfNaturalEmotion

    # Assuming you have the following variables with their respective times in seconds
    variables = [
        "Wild hand or arm Movements",
        "Slumping",
        "Leaning Backwards",
        "Clenching",
        "Aggressive body posture",
        "ShruggingPose",
        "Touching Your Face",
        "Confusion",
        "Natural Emotion"
    ]

    times = [wildMovement_bad_time, slumpPse_bad_time,LeaningPose_bad_time, Clunching_bad_time, AggressivePose_bad_time,
                ShruggingPose_bad_time, FaceTouch_bad_time, Confuse_duration, natural_emotion]

    body_language_analysis_dictionary = dict()
    body_language_analysis_dictionary['wildMovement_bad_time']  = round(wildMovement_bad_time,2)
    body_language_analysis_dictionary['slumpPse_bad_time']      = round(slumpPse_bad_time,2)
    body_language_analysis_dictionary['LeaningPose_bad_time']   = round(LeaningPose_bad_time,2)
    body_language_analysis_dictionary['LeaningPose_bad_time']   = round(LeaningPose_bad_time,2)
    body_language_analysis_dictionary['Clunching_bad_time']     = round(Clunching_bad_time,2)
    body_language_analysis_dictionary['ShruggingPose_bad_time'] = round(ShruggingPose_bad_time,2)
    body_language_analysis_dictionary['FaceTouch_bad_time']     = round(FaceTouch_bad_time,2)
    body_language_analysis_dictionary['Confuse_duration']       = round(Confuse_duration,2)
    body_language_analysis_dictionary['natural_emotion']        = round(natural_emotion,2)
    
    return body_language_analysis_dictionary