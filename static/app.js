class UIManager {
    constructor() {
        this.inputText = document.getElementById('input-text');
        this.transcript = document.getElementById('transcript');
        this.reply = document.getElementById('reply');
        this.speakBtn = document.getElementById('speak-btn');
        this.stopBtn = document.getElementById('stop-btn');
        this.sendBtn = document.getElementById('send-btn');
        this.ttsCheckbox = document.getElementById('tts-checkbox');
        this.status = document.getElementById('status');
        this.playAudioBtn = document.getElementById('play-audio-btn');
        this.audioPlayer = document.getElementById('audio-player');
    }

    showStatus(message, type = 'info') {
        this.status.textContent = message;
        this.status.className = `status-message ${type}`;
        if (type !== 'error') {
            setTimeout(() => this.clearStatus(), 3000);
        }
    }

    clearStatus() {
        this.status.textContent = '';
        this.status.className = 'status-message';
    }

    setTranscript(text) {
        this.transcript.textContent = text;
        this.transcript.classList.remove('error', 'loading');
    }

    setReply(text, isError = false) {
        this.reply.textContent = text;
        this.reply.classList.toggle('error', isError);
        this.reply.classList.remove('loading');
    }

    setLoading(elementId) {
        const element = document.getElementById(elementId);
        element.classList.add('loading');
        element.textContent = 'Processing...';
    }

    playAudio(audioBase64, sampleRate) {
        const binaryString = atob(audioBase64);
        const bytes = new Uint8Array(binaryString.length);
        for (let i = 0; i < binaryString.length; i++) {
            bytes[i] = binaryString.charCodeAt(i);
        }
        
        const blob = new Blob([bytes], { type: 'audio/wav' });
        const url = URL.createObjectURL(blob);
        
        this.audioPlayer.src = url;
        this.audioPlayer.play().catch(err => {
            this.showStatus(`Error playing audio: ${err.message}`, 'error');
        });
    }
}

class AudioRecorder {
    constructor() {
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.stream = null;
    }

    async start() {
        try {
            this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            this.mediaRecorder = new MediaRecorder(this.stream);
            this.audioChunks = [];

            this.mediaRecorder.ondataavailable = (event) => {
                this.audioChunks.push(event.data);
            };

            this.mediaRecorder.start();
            return true;
        } catch (error) {
            throw new Error(`Microphone access denied: ${error.message}`);
        }
    }

    stop() {
        return new Promise((resolve) => {
            this.mediaRecorder.onstop = () => {
                const audioBlob = new Blob(this.audioChunks, { type: 'audio/wav' });
                this.stream.getTracks().forEach(track => track.stop());
                resolve(audioBlob);
            };
            this.mediaRecorder.stop();
        });
    }
}

class VTCApp {
    constructor() {
        this.ui = new UIManager();
        this.recorder = new AudioRecorder();
        this.isRecording = false;
        this.lastReplyAudio = null;

        this.setupEventListeners();
    }

    setupEventListeners() {
        this.ui.speakBtn.addEventListener('click', () => this.startRecording());
        this.ui.stopBtn.addEventListener('click', () => this.stopRecording());
        this.ui.sendBtn.addEventListener('click', () => this.sendMessage());
        this.ui.playAudioBtn.addEventListener('click', () => this.playLastAudio());
    }

    async startRecording() {
        try {
            this.ui.showStatus('Starting recording...', 'info');
            await this.recorder.start();
            this.isRecording = true;

            this.ui.speakBtn.disabled = true;
            this.ui.speakBtn.classList.add('recording');
            this.ui.stopBtn.disabled = false;

            this.ui.setTranscript('Recording... Click Stop when finished.');
        } catch (error) {
            this.ui.showStatus(`Recording error: ${error.message}`, 'error');
            this.isRecording = false;
        }
    }

    async stopRecording() {
        try {
            this.ui.setTranscript('Processing audio...');
            const audioBlob = await this.recorder.stop();
            this.isRecording = false;

            this.ui.speakBtn.disabled = false;
            this.ui.speakBtn.classList.remove('recording');
            this.ui.stopBtn.disabled = true;

            await this.transcribeAudio(audioBlob);
        } catch (error) {
            this.ui.showStatus(`Stop recording error: ${error.message}`, 'error');
            this.isRecording = false;
        }
    }

    async transcribeAudio(audioBlob) {
        try {
            this.ui.setLoading('transcript');

            const formData = new FormData();
            formData.append('audio', audioBlob, 'audio.wav');

            const response = await fetch('/api/transcribe', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error(`Server error: ${response.status}`);
            }

            const data = await response.json();

            if (data.success) {
                const transcript = data.transcript || '(No speech detected)';
                this.ui.setTranscript(transcript);
                this.ui.inputText.value = transcript;
                this.ui.showStatus('Transcription complete!', 'success');
            } else {
                this.ui.setTranscript(`Error: ${data.error}`);
                this.ui.showStatus(`Transcription failed: ${data.error}`, 'error');
            }
        } catch (error) {
            this.ui.setTranscript(`Error: ${error.message}`);
            this.ui.showStatus(`Transcription error: ${error.message}`, 'error');
        }
    }

    async sendMessage() {
        try {
            let userText = this.ui.inputText.value.trim();

            if (!userText) {
                this.ui.showStatus('Please enter text or record audio first.', 'error');
                return;
            }

            this.ui.setLoading('reply');
            this.ui.showStatus('Generating reply...', 'info');

            const response = await fetch('/api/generate-reply', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: userText })
            });

            if (!response.ok) {
                throw new Error(`Server error: ${response.status}`);
            }

            const data = await response.json();

            if (data.success) {
                this.ui.setReply(data.reply);
                this.ui.showStatus('Reply generated!', 'success');

                if (this.ui.ttsCheckbox.checked) {
                    await this.synthesizeAndPlaySpeech(data.reply);
                }
            } else {
                this.ui.setReply(`Error: ${data.error}`, true);
                this.ui.showStatus(`Failed to generate reply: ${data.error}`, 'error');
            }
        } catch (error) {
            this.ui.setReply(`Error: ${error.message}`, true);
            this.ui.showStatus(`Error: ${error.message}`, 'error');
        }
    }

    async synthesizeAndPlaySpeech(text) {
        try {
            this.ui.showStatus('Synthesizing speech...', 'info');

            const response = await fetch('/api/synthesize-speech', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: text })
            });

            if (!response.ok) {
                throw new Error(`Server error: ${response.status}`);
            }

            const data = await response.json();

            if (data.success) {
                this.lastReplyAudio = data.audio;
                this.ui.playAudioBtn.style.display = 'inline-flex';
                this.ui.playAudioBtn.textContent = '🔊 Play Audio Reply';
                this.ui.showStatus('Speech synthesized! Playing...', 'success');
                this.ui.playAudio(data.audio, data.sample_rate);
            } else {
                this.ui.showStatus(`TTS failed: ${data.error}`, 'error');
            }
        } catch (error) {
            this.ui.showStatus(`Speech synthesis error: ${error.message}`, 'error');
        }
    }

    playLastAudio() {
        if (this.lastReplyAudio) {
            this.ui.playAudio(this.lastReplyAudio, 24000);
        }
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.app = new VTCApp();
});
