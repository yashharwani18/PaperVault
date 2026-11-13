# Android voice decision - 18 October 2026

User preference: Android on-device recognition when available, typed search otherwise. No bundled speech model or online recognition fallback.

Speech recognition turns audio into an editable text query; Qwen and EmbeddingGemma do not perform transcription in this app. The PC app remains typed-input only.

For the native Android implementation, check `SpeechRecognizer.isOnDeviceRecognitionAvailable`, then use `createOnDeviceSpeechRecognizer` (API 31+). On supported newer Android versions, check the requested language using `checkRecognitionSupport`. On failure, retain typed input. Availability and Hindi/Hinglish accuracy require a target-device test. [Official recognizer reference](https://developer.android.com/reference/android/speech/SpeechRecognizer).

Request microphone access only when the user invokes voice input. Show the transcript before searching, especially its numbers, dates and names. Do not silently switch to a general/default recognition service that may use a network. An offline preference flag alone is insufficient assurance of the chosen service's behavior. [Official intent reference](https://developer.android.com/reference/android/speech/RecognizerIntent).

Implemented in the standalone Android preview on 22 October 2026. The availability gate and typed fallback are present; spoken recognition accuracy and microphone interaction have not been tested on a physical phone. Phone model, Android version and installed speech languages remain unknown. Do not automatically download speech-language assets without an explicit user-facing action.
