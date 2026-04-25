# ============= Start to Remove Print Condition ====================


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
            # print(results.face_landmarks)

            # face_landmarks, pose_landmarks, left_hand_landmarks, right_hand_landmarks

            # Recolor image back to BGR for rendering
            image.flags.writeable = True
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

            # >>>>>>>>>>>>>>>>>-----------  Draw Landmarks------------>>>>>>>>>>>>>>>>>

            # 1. Draw face landmarks
            mp_drawing.draw_landmarks(image, results.face_landmarks, mp_holistic.FACEMESH_TESSELATION,
                                    mp_drawing.DrawingSpec(color=(80,110,10), thickness=1, circle_radius=1),
                                    mp_drawing.DrawingSpec(color=(80,256,121), thickness=1, circle_radius=1)
                                    )

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

                # Concate rows
                row = pose_row+face_row


                # Export to CSV
                with open('./assets/coords_pred.csv', mode='a', newline='') as f:
                    csv_writer = csv.writer(f, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
                    csv_writer.writerow(face_row)

            except:
                pass


            # >>>>>>>>>>>>>>>>>-----------  Exctract Landmarks------------>>>>>>>>>>>>>>>>>

            # posture landmarks

            shoulder = [results.pose_landmarks.landmark[11].x, results.pose_landmarks.landmark[11].y]
            shoulder_R = [results.pose_landmarks.landmark[12].x, results.pose_landmarks.landmark[11].y]


            right_shoulder_x = results.pose_landmarks.landmark[12].x
            right_shoulder_y = results.pose_landmarks.landmark[12].y
            right_shoulder_z = results.pose_landmarks.landmark[12].z
            left_shoulder_x = results.pose_landmarks.landmark[11].x
            left_shoulder_y = results.pose_landmarks.landmark[11].y
            left_shoulder_z = results.pose_landmarks.landmark[11].z

            midPoint_shoulder = (right_shoulder_x + left_shoulder_x)/2

            shoulder_Dist = right_shoulder_x - left_shoulder_x
            # print (f"=====================  Shoulder Distance =================\n Shoulder Distance = {shoulder_Dist}\n")

            elbow = [results.pose_landmarks.landmark[13].x, results.pose_landmarks.landmark[13].y]
            elbow_R = [results.pose_landmarks.landmark[14].x, results.pose_landmarks.landmark[14].y]

            wrist = [results.pose_landmarks.landmark[15].x, results.pose_landmarks.landmark[15].y]
            wrist_R = [results.pose_landmarks.landmark[16].x, results.pose_landmarks.landmark[16].y]

            knee_right = [results.pose_landmarks.landmark[26].x, results.pose_landmarks.landmark[26].y]
            knee_left = [results.pose_landmarks.landmark[25].x, results.pose_landmarks.landmark[25].y]

            right_knee_x = results.pose_landmarks.landmark[26].x
            right_knee_y = results.pose_landmarks.landmark[26].y
            right_knee_z = results.pose_landmarks.landmark[26].z
            left_knee_x = results.pose_landmarks.landmark[25].x
            left_knee_y = results.pose_landmarks.landmark[25].y
            left_knee_z = results.pose_landmarks.landmark[25].z

            midPoint_knee = (right_knee_x + left_knee_y)/2

            hip_right = [results.pose_landmarks.landmark[24].x, results.pose_landmarks.landmark[24].y]
            hip_left = [results.pose_landmarks.landmark[23].x, results.pose_landmarks.landmark[23].y]

            ear_left  = [results.pose_landmarks.landmark[7].x, results.pose_landmarks.landmark[7].y]
            ear_right = [results.pose_landmarks.landmark[8].x, results.pose_landmarks.landmark[8].y]

            mouth_right = [results.pose_landmarks.landmark[10].y]
            mouth_left = [results.pose_landmarks.landmark[9].y]

            nose = [results.pose_landmarks.landmark[0].x, results.pose_landmarks.landmark[0].y]

# ===========================================  Updated Code ==================================================

            # index_tip_right = [results.right_hand_landmarks.landmark[8].x, results.right_hand_landmarks.landmark[8].y]
            # index_pip_right = [results.right_hand_landmarks.landmark[6].x, results.right_hand_landmarks.landmark[6].y]
            # index_mcp_right = [results.right_hand_landmarks.landmark[5].x, results.right_hand_landmarks.landmark[5].y]

            # # for touch face
            # index_fingure_right_x =  results.right_hand_landmarks.landmark[8].x
            # index_fingure_right_y =  results.right_hand_landmarks.landmark[8].y

            # # Get the coordinates of the left wrist landmark at index 0
            # index_tip_left = [results.left_hand_landmarks.landmark[8].x, results.left_hand_landmarks.landmark[8].y]
            # index_pip_left = [results.left_hand_landmarks.landmark[6].x, results.left_hand_landmarks.landmark[6].y]
            # index_mcp_left = [results.left_hand_landmarks.landmark[5].x, results.left_hand_landmarks.landmark[5].y]

            # index_fingure_left_x =  results.left_hand_landmarks.landmark[8].x
            # index_fingure_left_y =  results.left_hand_landmarks.landmark[8].y

# ===========================================  Updated Code End ==================================================
            

            # Hand landmark
            # index_tip_right = None
            # index_pip_right = None
            # index_mcp_right = None
            # index_fingure_right_x = None
            # index_fingure_right_y = None


            # index_tip_left =None
            # index_pip_left = None
            # index_mcp_left = None

            # index_fingure_left_x =None
            # index_fingure_left_y = None
            # Check if the right wrist is open
            if results.right_hand_landmarks:
                # Get the coordinates of the right wrist landmark at index 0

                index_tip_right = [results.right_hand_landmarks.landmark[8].x, results.right_hand_landmarks.landmark[8].y]
                index_pip_right = [results.right_hand_landmarks.landmark[6].x, results.right_hand_landmarks.landmark[6].y]
                index_mcp_right = [results.right_hand_landmarks.landmark[5].x, results.right_hand_landmarks.landmark[5].y]

                pinky_tip_right = [results.right_hand_landmarks.landmark[20].x, results.right_hand_landmarks.landmark[20].y]
                pinky_pip_right = [results.right_hand_landmarks.landmark[18].x, results.right_hand_landmarks.landmark[18].y]
                pinky_mcp_right = [results.right_hand_landmarks.landmark[17].x, results.right_hand_landmarks.landmark[17].y]

                # for touch face
                index_fingure_right_x =  results.right_hand_landmarks.landmark[8].x
                index_fingure_right_y =  results.right_hand_landmarks.landmark[8].y

            # Check if the left wrist is open
            if results.left_hand_landmarks:

                # Get the coordinates of the left wrist landmark at index 0
                index_tip_left = [results.left_hand_landmarks.landmark[8].x, results.left_hand_landmarks.landmark[8].y]
                index_pip_left = [results.left_hand_landmarks.landmark[6].x, results.left_hand_landmarks.landmark[6].y]
                index_mcp_left = [results.left_hand_landmarks.landmark[5].x, results.left_hand_landmarks.landmark[5].y]

                pinky_tip_left = [results.left_hand_landmarks.landmark[20].x, results.left_hand_landmarks.landmark[20].y]
                pinky_pip_left = [results.left_hand_landmarks.landmark[18].x, results.left_hand_landmarks.landmark[18].y]
                pinky_mcp_left = [results.left_hand_landmarks.landmark[17].x, results.left_hand_landmarks.landmark[17].y]

                # index_fingure_left_y =  results.right_hand_landmarks.landmark[8].x
                index_fingure_left_x =  results.left_hand_landmarks.landmark[8].x
                index_fingure_left_y =  results.left_hand_landmarks.landmark[8].y




            # >>>>>>>>>>>>>>>>>-----------  Calculate Angles ------------>>>>>>>>>>>>>>>>>

                # calculate agnle for shurugging

                # Calculate distance between left shoulder and right shoulder points.
                shrug_dist_left = findDistance(results.pose_landmarks.landmark[11].x*w, results.pose_landmarks.landmark[11].y*h, results.pose_landmarks.landmark[7].x*w, results.pose_landmarks.landmark[7].y*h)
                shrug_dist_right = findDistance(results.pose_landmarks.landmark[12].x*w, results.pose_landmarks.landmark[12].y*h, results.pose_landmarks.landmark[8].x*w, results.pose_landmarks.landmark[8].y*h)

                # print(f"shrugging distance leftShoulder  = {shrug_dist_left:.2f}   and Counter = {shrugiing_counter:.2f}/{3}")
                # print(f"shrugging distance rightShoulder = {shrug_dist_right:.2f}  and Counter = {shrugiing_counter:.2f}/{3}")


                # calculate angle for aggressive or defensive

                # Right
                aggressive_angle_right = calculate_angle(wrist_R,shoulder_R,shoulder)
                # Left
                aggressive_angle_left = calculate_angle(wrist,shoulder,shoulder_R)

                # print(f"Aggressive angle right arm = {aggressive_angle_right:.2f} and Counter = {agressive_counter:.2f}/{5}")
                # print(f"Aggressive angle left arm  = {aggressive_angle_left:.2f}  and Counter = {agressive_counter:.2f}/{5}")

                # Calculate angle for wild movement
                angle = calculate_angle(shoulder, elbow, wrist)
                angle_R = calculate_angle(shoulder_R, elbow_R, wrist_R)
                # print(f"wild_Movement angle Left arm  = {angle:.2f}   and Counter = {counter:.2f}/{6}")
                # print(f"wild_Movement angle right arm = {angle_R:.2f} and Counter = {counter:.2f}/{6}")

                # Calculate angle for slumping leaning

                left_shoulder_knee_angle  = findDistance(left_shoulder_y*w,left_shoulder_z *h, left_knee_y*w, left_knee_z*h)
                right_shoulder_knee_angle  = findDistance(right_shoulder_y*w,right_shoulder_z *h, right_knee_y*w, right_knee_z*h)

                # print(f"slump/leaning angle left shoulderKnee = {left_shoulder_knee_angle:.2f}   and Slump-Counter = {slump_counter:.2f}/{4} and leaning-counter {leaning_backword_counter:.2f}")
                # print(f"slump/leaning angle right shoulderKnee = {right_shoulder_knee_angle:.2f} and Slump-Counter = {slump_counter:.2f}/{4} and leaning-counter {leaning_backword_counter:.2f}")


                # Calculate angle for clunching (close or open wrist)
                # left hand's fingures
                angle_LeftIndexFingure = calculate_angle(index_tip_left, index_pip_left, index_mcp_left)
                angle_rightIndexFingure = calculate_angle(index_tip_right, index_pip_right, index_mcp_right)

                # print(f"Clucnhing angle left indexFingure  = {angle_LeftIndexFingure:.2f}  and Counter = {clunch_counter:.2f}/{10}")
                # print(f"Clucnhing angle right indexFingure = {angle_rightIndexFingure:.2f} and Counter = {clunch_counter:.2f}/{10}")


                angle_touchingFace_leftHand = findDistance(results.pose_landmarks.landmark[0].x*w, results.pose_landmarks.landmark[0].y*h, index_fingure_left_x*w,index_fingure_left_y*h)
                angle_touchingFace_rightHand = findDistance(results.pose_landmarks.landmark[0].x*w, results.pose_landmarks.landmark[0].y*h, index_fingure_right_x*w,index_fingure_right_y*h)

                # print(f"Touching Face distance from right wrist  = {angle_touchingFace_rightHand:.2f} and Counter = {touchFace_counter:.2f}/{6} ")
                # print(f"Touching Face distance from left wrist   = {angle_touchingFace_leftHand:.2f}  and Counter = {touchFace_counter:.2f}/{6}")



                # print("\n\n---------------------------   Analysis of body postures ------------------------\n\n")




            # >>>>>>>>>>>>>>>>>-----------  Logic Building ------------>>>>>>>>>>>>>>>>>

                #  logic for shrugging

                if  shrug_dist_left <= 80 or shrug_dist_left <=80:
                    shrugiing_counter +=1
                # if shrugiing_counter >=3:
                #     print("Shrugging pose")
                # else:
                #     print("Not Shrugging pose")

                # Logic for aggressiveness

                if aggressive_angle_right <= 20 or aggressive_angle_left <=20:
                    agressive_counter += 1
                # if agressive_counter >= 5:
                #     print("Aggressive body posture")
                # else:
                #     print("Not aggressive body posture")


                # LOGIC for clunching

                if  angle_LeftIndexFingure <=10 or angle_rightIndexFingure <=10:
                    clunch_counter+=1
                # if clunch_counter >=10:
                #     print("Clenching is occuring")
                # else:
                #     print("Clenching is NOT occuring")


                # Logic for detect Hands Touching on Face

                if angle_touchingFace_rightHand <= 60 or angle_touchingFace_leftHand <= 60:
                    touchFace_counter +=1
                # if touchFace_counter >= 10:
                #     print("Hands touching face")
                # else:
                #     print("Hands Not touching face")


                # LOGIC Slump,Leaning

                if left_shoulder_knee_angle >= 400 and left_shoulder_knee_angle <= 500:
                    status = 'notSlump'
                else:
                    
                    if left_shoulder_knee_angle > 500:
                        slump_counter +=1     
                        # print(f"left side slump angle = {left_shoulder_knee_angle}\n and leaning_backword_counter = {leaning_backword_counter}")
                        
                    elif left_shoulder_knee_angle < 400:
                        leaning_backword_counter +=1
                        # print(f"left side slump angle = {left_shoulder_knee_angle}\n and slump_counter = {slump_counter}")

                        
                # print(f"======================================= Angle of Slump ============================\n")
                
                
                # print(f"======================================= End of Angle of Slump ============================\n")
                
                # if slump_counter >= 4:
                #     print("Slumping Pose")
                # elif leaning_backword_counter >=4:
                #     print("Leaning Pose")
                # else:
                #     print("Not Slumping")


                # LOGIC for Wild hand movements

                if angle > 160 or angle_R > 160:
                    counter +=1
                if angle < 30 or angle_R < 30:
                    counter +=1
                # if counter >=6:# set threshold for wild arm movements
                #     print("Wild Hand and Arm Movement")
                # else:
                #     print("Soft movements of hands")

            # cv2.imshow('body frames',image)

            if cv2.waitKey(10) & 0xFF == ord('q'):
                break

    cap.release()
    cv2.destroyAllWindows()

    df = pd.read_csv('./assets/coords_pred.csv')
    Prediction_data = df
    yhat = model.predict(Prediction_data)
    # print(f"prediction  = {yhat} \n and type = {type(yhat)} ")


    # Assuming yhat is your array of predictions
    predictions_counter = Counter(yhat)

    # Count occurrences of "natural" and "unhappy/shocked"
    natural_count = predictions_counter["natural"]
    unhappy_shocked_count = predictions_counter["unhappy/shocked"]

    # print(f"Occurrences of 'natural': {natural_count}")
    # print(f"Occurrences of 'unhappy/shocked': {unhappy_shocked_count}")

    sumOfemotion = natural_count+unhappy_shocked_count
    percent_OfNaturalEmotion = (natural_count/sumOfemotion)*100
    percent_of_OfUnhappyEmotion = (unhappy_shocked_count/sumOfemotion)*100



    # Occurrences_of_natural_emotion = 46
    # Occurrences_of_confusion = 114  #unhappy/shocked

    wildMovement_bad_time =  (1 / 30) * counter
    slumpPse_bad_time =  (1 / 30) * slump_counter
    LeaningPose_bad_time =  (1 / 30) * leaning_backword_counter
    Clunching_bad_time =  (1 / 30) * clunch_counter
    AggressivePose_bad_time =  (1 / 30) * agressive_counter
    ShruggingPose_bad_time =  (1 / 30) * shrugiing_counter
    FaceTouch_bad_time =  (1 / 30) * touchFace_counter
    Confuse_duration = (1 / 30) * percent_of_OfUnhappyEmotion
    natural_emotion = (1 / 30) * percent_OfNaturalEmotion

    # print(f"wildMovement_bad_time = {wildMovement_bad_time:.2f}s")
    # print(f"slumpPse_bad_time = {slumpPse_bad_time:.2f}s")
    # print(f"LeaningPose_bad_time = {LeaningPose_bad_time:.2f}s")
    # print(f"Clunching_bad_time = {Clunching_bad_time:.2f}s")
    # print(f"AggressivePose_bad_time = {AggressivePose_bad_time:.2f}s")
    # print(f"ShruggingPose_bad_time = {ShruggingPose_bad_time:.2f}s")
    # print(f"FaceTouch_bad_time = {FaceTouch_bad_time:.2f}s")
    # print(f"Confuse_duration = {Confuse_duration:.2f}s")
    # print(f"Good face emotion time = {natural_emotion:.2f}s")


    # print("\n\n----------------  Body Language Analysis  -------------------\n\n")

    # print("Accoding to your interview you have spent time(seconds) on diffirent body pose such as follow: \n\n")

    # print(f"During the interview, you exhibited erratic hand or arm movements for  {wildMovement_bad_time:.2f} seconds")
    # print(f"During the interview, you maintain a slumped posture for               {slumpPse_bad_time:.2f} seconds")
    # print(f"During interview, you stay in Leaning Backwards pose for               {LeaningPose_bad_time:.2f} seconds")
    # print(f"During the interview, you remained in a posture leaning backwards for  {Clunching_bad_time:.2f} seconds")
    # print(f"During the interview, you displayed signs of aggression for            {AggressivePose_bad_time:.2f} seconds")
    # print(f"During the interview, you maintained a shrugging posture for           {ShruggingPose_bad_time:.2f} seconds")
    # print(f"During the interview, you repeatedly touched your face for             {FaceTouch_bad_time:.2f} seconds")
    # print(f"During the interview, you appeared perplexed for                       {Confuse_duration:.2f} seconds")
    # print(f"During the interview, you appeared composed for                        {natural_emotion:.2f} seconds\n\n")


    # print(f"----The following graph illustrates the body posture and emotional changes over time---\n\n")

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

    # # Plotting the bar chart
    # plt.figure(figsize=(10, 6))
    # plt.bar(variables, times, color='skyblue')
    # plt.xlabel('Variables')
    # plt.ylabel('Time (seconds)')
    # plt.title('Time Duration for Different Variables')
    # plt.xticks(rotation=45, ha='right')  # Rotate x-axis labels for better readability
    # plt.tight_layout()  # Adjust layout to prevent clipping of labels
    # plt.show()

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