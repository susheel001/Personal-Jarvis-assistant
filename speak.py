"""
speak.py — Jarvis Voice & Personality
"""
import pyttsx3
import datetime
import random

class JarvisVoice:
    def __init__(self):
        self.engine = None
        self.voice_backend = "print"

        try:
            import win32com.client

            self.engine = win32com.client.Dispatch("SAPI.SpVoice")
            self.engine.Rate = -1
            self.engine.Volume = 95

            voices = self.engine.GetVoices()
            for i in range(voices.Count):
                voice = voices.Item(i)
                if any(name in voice.GetDescription().lower() for name in ['male', 'david', 'mark', 'george', 'james']):
                    self.engine.Voice = voice
                    break
            self.voice_backend = "sapi"
            print("[Jarvis] Using Windows SAPI voice.")
            return
        except Exception as e:
            print(f"[Jarvis] Windows SAPI voice unavailable: {e}")

        try:
            self.engine = pyttsx3.init()
            self.engine.setProperty('rate', 165)
            self.engine.setProperty('volume', 0.95)

            # Set male voice
            voices = self.engine.getProperty('voices')
            for voice in voices:
                if any(name in voice.name.lower() for name in ['male', 'david', 'mark', 'george', 'james']):
                    self.engine.setProperty('voice', voice.id)
                    break
            self.voice_backend = "pyttsx3"
            print("[Jarvis] Using pyttsx3 voice fallback.")
        except Exception as e:
            self.engine = None
            print(f"[Jarvis] Voice output unavailable, using text only: {e}")

    def speak(self, text):
        print(f"[Jarvis] {text}")
        if self.voice_backend == "pyttsx3":
            try:
                self.engine.say(text)
                self.engine.runAndWait()
                return
            except Exception as e:
                print(f"[Jarvis] pyttsx3 speak failed: {e}")
        elif self.voice_backend == "sapi":
            try:
                self.engine.Speak(text)
                return
            except Exception as e:
                print(f"[Jarvis] SAPI speak failed: {e}")

    def get_greeting(self):
        hour = datetime.datetime.now().hour
        name = "sir"
        if 5 <= hour < 12:
            time_greet = "Good morning"
        elif 12 <= hour < 17:
            time_greet = "Good afternoon"
        elif 17 <= hour < 21:
            time_greet = "Good evening"
        else:
            time_greet = "Good night"
        return f"{time_greet}, {name}."

    def startup_greeting(self):
        hour = datetime.datetime.now().hour
        greet = self.get_greeting()

        if 5 <= hour < 12:
            lines = [
                f"{greet} Jarvis is online and fully operational. Ready to assist you today.",
                f"{greet} All systems are up and running. What shall we accomplish today?",
                f"{greet} Jarvis reporting for duty. I hope you slept well, sir.",
            ]
        elif 12 <= hour < 17:
            lines = [
                f"{greet} Jarvis is online. Hope your day is going well, sir.",
                f"{greet} All systems operational. How can I assist you this afternoon?",
                f"{greet} Jarvis at your service. What do you need, sir?",
            ]
        elif 17 <= hour < 21:
            lines = [
                f"{greet} Jarvis is online. Had a long day, sir? I am here to help.",
                f"{greet} All systems ready. What can I do for you this evening?",
                f"{greet} Jarvis reporting in. Shall we wrap up the day together, sir?",
            ]
        else:
            lines = [
                f"{greet} Jarvis is online. Working late again, sir?",
                f"{greet} All systems operational. I will keep you company tonight.",
                f"{greet} Jarvis at your service, even at this hour, sir.",
            ]
        self.speak(random.choice(lines))

    def wake_word_response(self):
        responses = [
            "Yes sir?",
            "At your service, sir.",
            "How can I help you, sir?",
            "I am listening, sir.",
            "Yes? What do you need, sir?",
            "Ready, sir. Go ahead.",
        ]
        self.speak(random.choice(responses))

    def not_understood(self):
        responses = [
            "I am sorry sir, I did not quite catch that. Could you repeat?",
            "Pardon me sir, could you say that again?",
            "I did not understand that, sir. Please try again.",
            "My apologies sir, I missed that. Say it once more?",
        ]
        self.speak(random.choice(responses))

    def workspace_opening(self):
        responses = [
            "Of course sir. Opening your workspace right away.",
            "Right away sir. Launching all your applications.",
            "Sure thing sir. Setting up your workspace now.",
            "On it sir. Your workspace will be ready in a moment.",
        ]
        self.speak(random.choice(responses))

    def workspace_done(self):
        responses = [
            "Your workspace is all set, sir. Have a productive session!",
            "Everything is open and ready for you, sir.",
            "All done sir. Your workspace is ready to go!",
            "Your applications are up and running, sir.",
        ]
        self.speak(random.choice(responses))

    def waking_screen(self):
        responses = [
            "Waking up the screen, sir.",
            "Turning on the display, sir.",
            "Right away sir. Waking your screen now.",
        ]
        self.speak(random.choice(responses))

    def unlocking_screen(self):
        responses = [
            "Entering your password now, sir.",
            "Unlocking your system, sir.",
            "On it sir. Logging you in now.",
        ]
        self.speak(random.choice(responses))

    def unlocked_done(self):
        responses = [
            "You are logged in, sir. Welcome back.",
            "System unlocked, sir. Good to have you back.",
            "All done sir. You are in.",
        ]
        self.speak(random.choice(responses))

    def locking_screen(self):
        responses = [
            "Locking your screen, sir. Stay safe.",
            "Sure sir. Securing your system now.",
            "Locking up, sir. See you soon.",
            "Screen locked, sir. Take care.",
        ]
        self.speak(random.choice(responses))

    def no_internet(self):
        self.speak("I am sorry sir, it seems we have no internet connection. Please check your network and try again.")

    def goodbye(self):
        responses = [
            "Goodbye sir. Have a wonderful day!",
            "Shutting down sir. Take care!",
            "Farewell sir. It was a pleasure assisting you.",
            "Goodbye sir. See you soon!",
        ]
        self.speak(random.choice(responses))

    def unknown_command(self):
        responses = [
            "I am sorry sir, I am not sure how to help with that. Try saying: open workspace, wake screen, or lock screen.",
            "Hmm, I did not quite get that sir. You can say: open my workspace, wake up the screen, or lock the screen.",
            "Apologies sir, that is outside my current abilities. Try a different command.",
        ]
        self.speak(random.choice(responses))

    def standby(self):
        responses = [
            "Standing by, sir. Say Hey Jarvis whenever you need me.",
            "Ready and waiting, sir.",
            "All systems ready, sir. Just say the word.",
        ]
        self.speak(random.choice(responses))
