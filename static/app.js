/**
 * VTC AI - Modern Chat Interface with Voice & Visualizer
 */

class AudioVisualizer {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        this.audioContext = null;
        this.playbackAnalyser = null;
        this.micAnalyser = null;
        this.micSource = null;
        this.activeAnalyser = null;
        this.activeDataArray = null;
        this.animationId = null;
        this.isActive = false;

        this.resizeCanvas();
        window.addEventListener('resize', () => this.resizeCanvas());
    }

    resizeCanvas() {
        const container = this.canvas.parentElement;
        const dpr = window.devicePixelRatio || 1;
        const rect = container.getBoundingClientRect();

        this.canvas.width = rect.width * dpr;
        this.canvas.height = rect.height * dpr;
        this.ctx.scale(dpr, dpr);

        this.canvas.style.width = `${rect.width}px`;
        this.canvas.style.height = `${rect.height}px`;
    }

    ensureContext() {
        if (!this.audioContext) {
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
        }
        return this.audioContext;
    }

    // Original playback visualizer: hooked to the <audio> element used for TTS replies.
    setup(audioElement) {
        try {
            const ctx = this.ensureContext();
            const source = ctx.createMediaElementSource(audioElement);
            this.playbackAnalyser = ctx.createAnalyser();
            this.playbackAnalyser.fftSize = 256;
            this.playbackAnalyser.smoothingTimeConstant = 0.8;

            source.connect(this.playbackAnalyser);
            // Must connect to destination or the audio element goes silent.
            this.playbackAnalyser.connect(ctx.destination);

            console.log('Playback visualizer setup complete');
        } catch (error) {
            console.error('Failed to setup playback visualizer:', error);
            // Don't throw - allow audio to work without visualizer
        }
    }

    // New: hook the visualizer up to the user's live microphone stream so they
    // get visual feedback ("am I actually being heard?") while recording.
    setupMic(stream) {
        try {
            const ctx = this.ensureContext();
            if (this.micSource) {
                this.micSource.disconnect();
            }
            this.micSource = ctx.createMediaStreamSource(stream);
            if (!this.micAnalyser) {
                this.micAnalyser = ctx.createAnalyser();
                this.micAnalyser.fftSize = 256;
                this.micAnalyser.smoothingTimeConstant = 0.6;
            }
            // Intentionally NOT connected to ctx.destination - connecting a live
            // mic straight to the speakers would cause an audio feedback loop.
            this.micSource.connect(this.micAnalyser);
            console.log('Mic visualizer setup complete');
        } catch (error) {
            console.error('Failed to setup mic visualizer:', error);
        }
    }

    teardownMic() {
        if (this.micSource) {
            try { this.micSource.disconnect(); } catch (e) { /* already disconnected */ }
            this.micSource = null;
        }
    }

    start(mode = 'playback') {
        this.activeAnalyser = mode === 'mic' ? this.micAnalyser : this.playbackAnalyser;
        this.activeDataArray = this.activeAnalyser
            ? new Uint8Array(this.activeAnalyser.frequencyBinCount)
            : null;

        if (this.isActive) return;
        this.isActive = true;
        this.canvas.parentElement.classList.add('active');

        // Resume AudioContext if suspended (browser autoplay policy)
        if (this.audioContext && this.audioContext.state === 'suspended') {
            this.audioContext.resume().then(() => {
                console.log('AudioContext resumed');
            });
        }

        this.animate();
    }

    stop() {
        this.isActive = false;
        this.canvas.parentElement.classList.remove('active');
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
            this.animationId = null;
        }
        this.clear();
    }

    disconnect() {
        this.stop();
        this.teardownMic();
        if (this.playbackAnalyser) {
            this.playbackAnalyser.disconnect();
            this.playbackAnalyser = null;
        }
    }

    animate() {
        if (!this.isActive) return;

        this.animationId = requestAnimationFrame(() => this.animate());

        if (!this.activeAnalyser || !this.activeDataArray) {
            this.drawBars([]);
            return;
        }

        this.activeAnalyser.getByteFrequencyData(this.activeDataArray);
        const frequencies = Array.from(this.activeDataArray);
        this.drawBars(frequencies);
    }

    drawBars(frequencies) {
        const width = this.canvas.width / (window.devicePixelRatio || 1);
        const height = this.canvas.height / (window.devicePixelRatio || 1);
        const barCount = 32;
        const barWidth = (width - (barCount - 1) * 2) / barCount;
        const maxHeight = height * 0.8;

        this.ctx.clearRect(0, 0, width, height);

        const gradient = this.ctx.createLinearGradient(0, height, 0, height - maxHeight);
        gradient.addColorStop(0, '#10a37f');
        gradient.addColorStop(1, '#3b82f6');

        for (let i = 0; i < barCount; i++) {
            const frequencyIndex = Math.floor((i / barCount) * frequencies.length);
            const value = frequencies[frequencyIndex] || 0;
            const normalizedValue = value / 255;
            const barHeight = Math.max(4, normalizedValue * maxHeight);
            const x = i * (barWidth + 2);
            const y = height - barHeight;

            this.ctx.fillStyle = gradient;
            this.ctx.beginPath();
            this.roundRect(x, y, barWidth, barHeight, barWidth / 2);
            this.ctx.fill();
        }
    }

    roundRect(x, y, width, height, radius) {
        this.ctx.moveTo(x + radius, y);
        this.ctx.lineTo(x + width - radius, y);
        this.ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
        this.ctx.lineTo(x + width, y + height - radius);
        this.ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
        this.ctx.lineTo(x + radius, y + height);
        this.ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
        this.ctx.lineTo(x, y + radius);
        this.ctx.quadraticCurveTo(x, y, x + radius, y);
    }

    clear() {
        const width = this.canvas.width / (window.devicePixelRatio || 1);
        const height = this.canvas.height / (window.devicePixelRatio || 1);
        this.ctx.clearRect(0, 0, width, height);
    }
}

class ChatUI {
    constructor() {
        this.chatContainer = document.getElementById('chat-container');
        this.messagesList = document.getElementById('messages-list');
        this.messageInput = document.getElementById('message-input');
        this.micBtn = document.getElementById('mic-btn');
        this.sendBtn = document.getElementById('send-btn');
        this.themeToggle = document.getElementById('theme-toggle');
        this.newChatBtn = document.getElementById('new-chat-btn');
        this.statusToast = document.getElementById('status-toast');
        this.audioPlayer = document.getElementById('audio-player');
        this.messageCounter = 0;

        this.setupEventListeners();
        this.setupTheme();
    }

    setupEventListeners() {
        this.messageInput.addEventListener('input', () => this.handleInputChange());
        this.messageInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.handleSend();
            }
        });

        this.sendBtn.addEventListener('click', () => this.handleSend());
        this.micBtn.addEventListener('click', () => this.handleMicToggle());
        this.themeToggle.addEventListener('click', () => this.toggleTheme());
        this.newChatBtn.addEventListener('click', () => {
            window.dispatchEvent(new CustomEvent('newChat'));
        });

        // Auto-resize textarea
        this.messageInput.addEventListener('input', () => {
            this.messageInput.style.height = 'auto';
            this.messageInput.style.height = Math.min(this.messageInput.scrollHeight, 200) + 'px';
        });
    }

    setupTheme() {
        const savedTheme = localStorage.getItem('theme') || 'dark';
        document.documentElement.setAttribute('data-theme', savedTheme);
    }

    toggleTheme() {
        const currentTheme = document.documentElement.getAttribute('data-theme');
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', newTheme);
        localStorage.setItem('theme', newTheme);
    }

    handleInputChange() {
        const hasText = this.messageInput.value.trim().length > 0;
        this.sendBtn.disabled = !hasText;
    }

    handleSend() {
        const text = this.messageInput.value.trim();
        if (!text) return;

        // Trigger custom event for app to handle
        window.dispatchEvent(new CustomEvent('sendMessage', { detail: { text } }));

        // Clear input
        this.messageInput.value = '';
        this.messageInput.style.height = 'auto';
        this.sendBtn.disabled = true;
    }

    handleMicToggle() {
        // Trigger custom event for app to handle
        window.dispatchEvent(new CustomEvent('toggleRecording'));
    }

    addWelcomeMessage() {
        // Welcome message is already in HTML
    }

    clearMessages() {
        this.messagesList.innerHTML = '';
        this.messageCounter = 0;
        const welcomeMsg = document.querySelector('.welcome-message');
        if (welcomeMsg) {
            welcomeMsg.style.display = '';
        }
    }

    addMessage(role, text, isLoading = false) {
        // Remove welcome message if exists
        const welcomeMsg = document.querySelector('.welcome-message');
        if (welcomeMsg) {
            welcomeMsg.style.display = 'none';
        }

        const messageId = `msg-${++this.messageCounter}-${Date.now()}`;
        const messageWrapper = document.createElement('div');
        messageWrapper.className = `message-wrapper ${role}-message`;
        messageWrapper.id = messageId;
        messageWrapper.setAttribute('data-role', role);
        messageWrapper.setAttribute('data-sequence', this.messageCounter);

        const avatarSvg = role === 'assistant'
            ? `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8z"/>
                <path d="M12 6v6l4 2"/>
               </svg>`
            : `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                <circle cx="12" cy="7" r="4"/>
               </svg>`;

        const roleLabel = role === 'assistant' ? 'SAGE' : 'You';

        messageWrapper.innerHTML = `
            <div class="message-avatar">
                ${avatarSvg}
            </div>
            <div class="message-content">
                <div class="message-role">${roleLabel}</div>
                <div class="message-text">${isLoading ? '<div class="typing-indicator"><span></span><span></span><span></span></div>' : this.formatText(text)}</div>
            </div>
        `;

        this.messagesList.appendChild(messageWrapper);
        this.scrollToBottom();

        return messageId;
    }

    updateMessage(messageId, text) {
        const messageWrapper = document.getElementById(messageId);
        if (!messageWrapper) return;

        const messageText = messageWrapper.querySelector('.message-text');
        if (messageText) {
            messageText.innerHTML = this.formatText(text);
        }
        this.scrollToBottom();
    }

    formatText(text) {
        // Escape HTML
        let formatted = text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');

        // Convert URLs to links
        formatted = formatted.replace(
            /(https?:\/\/[^\s]+)/g,
            '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>'
        );

        // Convert line breaks to paragraphs
        const paragraphs = formatted.split('\n\n');
        formatted = paragraphs.map(p => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('');

        return formatted;
    }

    scrollToBottom() {
        this.chatContainer.scrollTop = this.chatContainer.scrollHeight;
    }

    showStatus(message, type = 'info') {
        const statusText = this.statusToast.querySelector('.status-text');
        statusText.textContent = message;

        this.statusToast.className = 'status-toast show';
        if (type) {
            this.statusToast.classList.add(type);
        }

        clearTimeout(this.statusTimeout);
        this.statusTimeout = setTimeout(() => {
            this.statusToast.classList.remove('show');
        }, 3000);
    }

    setRecordingState(isRecording) {
        this.micBtn.classList.toggle('recording', isRecording);
        // NOTE: previously this also set `this.micBtn.disabled = isRecording`,
        // which made it impossible to click the button again to stop recording
        // (disabled buttons don't fire click events). Keep it enabled so a
        // second click always ends the user's turn.
        this.micBtn.title = isRecording ? 'Click to stop and send' : 'Record voice';

        const container = this.messageInput.closest('.input-container');
        if (container) {
            container.classList.toggle('listening', isRecording);
        }
    }

    updateTranscript(text) {
        // Update the last user message if exists
        const lastUserMessage = this.messagesList.querySelector('.user-message:last-child .message-text');
        if (lastUserMessage && !lastUserMessage.querySelector('.typing-indicator')) {
            lastUserMessage.innerHTML = this.formatText(text);
        }
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
            this.stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true
                }
            });
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
        return new Promise((resolve, reject) => {
            if (!this.mediaRecorder) {
                reject(new Error('No recording in progress'));
                return;
            }

            this.mediaRecorder.onstop = () => {
                const audioBlob = new Blob(this.audioChunks, { type: 'audio/wav' });
                this.stopTracks();
                resolve(audioBlob);
            };

            this.mediaRecorder.onerror = (event) => {
                this.stopTracks();
                reject(new Error('Recording error'));
            };

            this.mediaRecorder.stop();
        });
    }

    stopTracks() {
        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
        }
    }
}

/**
 * Best-effort LIVE captioning while the user speaks, using the browser's
 * built-in SpeechRecognition (Chrome/Edge/Safari support it; Firefox doesn't).
 * This is only used to show text in the input bar in real time - the actual
 * message that gets sent still comes from the accurate Groq transcription
 * of the recorded audio once the user stops recording.
 */
class LiveCaption {
    constructor() {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        this.supported = !!SR;
        if (this.supported) {
            this.recognition = new SR();
            this.recognition.continuous = true;
            this.recognition.interimResults = true;
            this.recognition.lang = 'en-US';
        }
        this.shouldRestart = false;
    }

    start(onUpdate) {
        if (!this.supported) return;

        this.finalText = '';
        this.shouldRestart = true;

        this.recognition.onresult = (event) => {
            let interim = '';
            let final = '';
            for (let i = event.resultIndex; i < event.results.length; i++) {
                const piece = event.results[i][0].transcript;
                if (event.results[i].isFinal) {
                    final += piece;
                } else {
                    interim += piece;
                }
            }
            this.finalText += final;
            onUpdate((this.finalText + ' ' + interim).trim());
        };

        this.recognition.onerror = (event) => {
            // "no-speech" / "aborted" fire routinely - not real errors, ignore them.
            if (event.error !== 'no-speech' && event.error !== 'aborted') {
                console.warn('Speech recognition error:', event.error);
            }
        };

        // Some browsers auto-stop recognition after a short silence even while
        // the user is still recording - restart it transparently so captions
        // keep flowing for as long as recording is active.
        this.recognition.onend = () => {
            if (this.shouldRestart) {
                try { this.recognition.start(); } catch (e) { /* already starting */ }
            }
        };

        try {
            this.recognition.start();
        } catch (e) {
            console.warn('Could not start live captioning:', e);
        }
    }

    stop() {
        this.shouldRestart = false;
        if (this.supported) {
            try { this.recognition.stop(); } catch (e) { /* not running */ }
        }
    }
}

class VTCApp {
    constructor() {
        this.ui = new ChatUI();
        this.recorder = new AudioRecorder();
        this.visualizer = new AudioVisualizer('audio-visualizer');
        this.caption = new LiveCaption();
        this.audioPlayer = document.getElementById('audio-player');
        this.volumeControl = document.getElementById('volume-control');
        this.volumeValue = document.getElementById('volume-value');
        const savedVolume = parseFloat(localStorage.getItem('sageVoiceVolume') || '1');
        this.voiceVolume = Number.isFinite(savedVolume) ? Math.min(1, Math.max(0, savedVolume)) : 1;
        this.audioPlayer.volume = this.voiceVolume;
        this.visualizerLabel = document.querySelector('.visualizer-label');

        this.isRecording = false;
        this.lastReplyAudio = null;
        this.pending = false;
        // Keep recent conversation context in the browser so serverless deployments
        // do not lose memory when requests land on different instances.
        try {
            this.conversationHistory = JSON.parse(localStorage.getItem('sageConversationHistory') || '[]');
            if (!Array.isArray(this.conversationHistory)) this.conversationHistory = [];
        } catch {
            this.conversationHistory = [];
        }

        // Browser location, so SAGE can answer "what's the weather/time" without
        // asking where you are, unless you name a different place.
        this.userLocation = { label: null, latitude: null, longitude: null };
        try {
            const cached = JSON.parse(localStorage.getItem('sageUserLocation') || 'null');
            if (cached && (cached.label || (cached.latitude && cached.longitude))) {
                this.userLocation = cached;
            }
        } catch { /* ignore malformed cache */ }
        this.initLocation();

        this.setupEventListeners();
        this.setupVisualizer();
    }

    initLocation() {
        if (!navigator.geolocation) return;

        navigator.geolocation.getCurrentPosition(
            async (position) => {
                const { latitude, longitude } = position.coords;
                this.userLocation.latitude = latitude;
                this.userLocation.longitude = longitude;
                const label = await this.reverseGeocode(latitude, longitude);
                if (label) this.userLocation.label = label;
                localStorage.setItem('sageUserLocation', JSON.stringify(this.userLocation));
            },
            (error) => {
                // Permission denied or unavailable - SAGE will just ask when it needs to know.
                console.warn('Geolocation unavailable:', error.message);
            },
            { enableHighAccuracy: false, timeout: 8000, maximumAge: 3600000 }
        );
    }

    async reverseGeocode(latitude, longitude) {
        try {
            const res = await fetch(
                `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${latitude}&lon=${longitude}&zoom=10`
            );
            if (!res.ok) return null;
            const data = await res.json();
            const addr = data.address || {};
            const city = addr.city || addr.town || addr.village || addr.suburb || addr.county;
            const region = addr.state;
            const country = addr.country;
            return [city, region, country].filter(Boolean).join(', ') || data.display_name || null;
        } catch (error) {
            console.warn('Reverse geocoding failed:', error);
            return null;
        }
    }

    setVisualizerLabel(text) {
        if (this.visualizerLabel) {
            this.visualizerLabel.textContent = text;
        }
    }

    setupEventListeners() {
        window.addEventListener('sendMessage', (e) => this.sendMessage(e.detail.text, { addUser: true }));
        window.addEventListener('toggleRecording', () => this.toggleRecording());
        window.addEventListener('newChat', () => this.resetConversation());
        if (this.volumeControl) {
            this.volumeControl.value = String(Math.round(this.voiceVolume * 100));
            this.updateVolumeLabel();
            this.volumeControl.addEventListener('input', () => {
                this.voiceVolume = Number(this.volumeControl.value) / 100;
                this.audioPlayer.volume = this.voiceVolume;
                localStorage.setItem('sageVoiceVolume', String(this.voiceVolume));
                this.updateVolumeLabel();
            });
        }
    }

    updateVolumeLabel() {
        if (this.volumeValue) this.volumeValue.textContent = `${Math.round(this.voiceVolume * 100)}%`;
    }

    async resetConversation() {
        // Clears both the visible chat and SAGE's server-side memory, so the
        // next message starts a genuinely fresh conversation.
        this.ui.clearMessages();
        this.conversationHistory = [];
        localStorage.removeItem('sageConversationHistory');
        try {
            await fetch('/api/reset-conversation', { method: 'POST' });
            this.ui.showStatus('Started a new chat', 'success');
        } catch (error) {
            this.ui.showStatus(`Could not reset memory: ${error.message}`, 'error');
        }
    }

    setupVisualizer() {
        this.visualizer.setup(this.audioPlayer);

        this.audioPlayer.addEventListener('play', () => {
            this.setVisualizerLabel('Playing response...');
            this.visualizer.start('playback');
        });

        this.audioPlayer.addEventListener('pause', () => {
            this.visualizer.stop();
        });

        this.audioPlayer.addEventListener('ended', () => {
            this.visualizer.stop();
        });
    }

    async toggleRecording() {
        if (this.isRecording) {
            await this.stopRecording();
        } else {
            await this.startRecording();
        }
    }

    async startRecording() {
        try {
            this.ui.showStatus('Listening...', 'info');
            await this.recorder.start();
            this.isRecording = true;
            this.ui.setRecordingState(true);
            this.ui.sendBtn.disabled = true;
            this.ui.showStatus('Recording... click the mic again when done', 'success');

            // Live mic-level visualizer so the user can SEE their voice is being picked up.
            if (this.recorder.stream) {
                this.visualizer.setupMic(this.recorder.stream);
                this.setVisualizerLabel('Listening...');
                this.visualizer.start('mic');
            }

            // Live captions: show what's being heard directly in the input bar
            // as the user talks (best-effort - falls back gracefully if the
            // browser doesn't support SpeechRecognition).
            this.ui.messageInput.value = '';
            this.ui.messageInput.readOnly = true;
            this.ui.messageInput.placeholder = this.caption.supported
                ? 'Listening...'
                : 'Listening... (live captions not supported in this browser)';
            this.caption.start((text) => {
                this.ui.messageInput.value = text;
            });
        } catch (error) {
            this.ui.showStatus(error.message, 'error');
            this.isRecording = false;
            this.ui.setRecordingState(false);
        }
    }

    async stopRecording() {
        try {
            this.ui.showStatus('Processing audio...', 'info');

            // Clicking the mic button again is the "I'm done talking" signal:
            // stop listening/captioning/visualizing, then hand things to the agent.
            this.caption.stop();
            this.visualizer.stop();
            this.visualizer.teardownMic();

            const audioBlob = await this.recorder.stop();
            this.isRecording = false;
            this.ui.setRecordingState(false);
            this.ui.messageInput.readOnly = false;
            this.ui.messageInput.value = '';
            this.ui.messageInput.placeholder = 'Send a message...';

            await this.transcribeAudio(audioBlob);
        } catch (error) {
            this.ui.showStatus(error.message, 'error');
            this.isRecording = false;
            this.ui.setRecordingState(false);
            this.ui.messageInput.readOnly = false;
            this.ui.messageInput.placeholder = 'Send a message...';
            this.caption.stop();
            this.visualizer.stop();
            this.visualizer.teardownMic();
        }
    }

    async transcribeAudio(audioBlob) {
        try {
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
                this.ui.showStatus('Transcription complete!', 'success');

                // Send and let sendMessage add the user bubble (single source of truth)
                await this.sendMessage(transcript, { addUser: true });
            } else {
                this.ui.showStatus(`Transcription failed: ${data.error}`, 'error');
            }
        } catch (error) {
            this.ui.showStatus(`Transcription error: ${error.message}`, 'error');
        }
    }

    async sendMessage(text, opts = {}) {
        const { addUser = true } = opts;
        const clean = (text || '').trim();
        if (!clean) return;
        if (this.pending) {
            console.warn('Request already pending, ignoring duplicate send');
            return;
        }
        this.pending = true;
        this.ui.sendBtn.disabled = true;
        this.ui.micBtn.disabled = true;

        try {
            this.ui.showStatus('Generating response...', 'info');

            // Always add the user bubble here when requested (single source of truth)
            if (addUser) {
                const userMsgId = this.ui.addMessage('user', clean);
                console.log('User message added:', userMsgId);
                // Force a small delay to ensure DOM update before adding assistant
                await new Promise(resolve => setTimeout(resolve, 10));
            }

            // Add loading assistant message and keep its id local to avoid races
            const assistantId = this.ui.addMessage('assistant', '', true);
            console.log('Assistant message added:', assistantId);

            const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
            const response = await fetch('/api/generate-reply', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    text: clean,
                    history: this.conversationHistory.slice(-24),
                    timezone,
                    location: this.userLocation.label,
                    latitude: this.userLocation.latitude,
                    longitude: this.userLocation.longitude
                })
            });

            if (!response.ok) {
                throw new Error(`Server error: ${response.status}`);
            }

            const data = await response.json();

            if (data.success) {
                this.ui.updateMessage(assistantId, data.reply);
                this.conversationHistory.push({ role: 'user', content: clean });
                this.conversationHistory.push({ role: 'assistant', content: data.reply });
                this.conversationHistory = this.conversationHistory.slice(-24);
                localStorage.setItem('sageConversationHistory', JSON.stringify(this.conversationHistory));
                this.ui.showStatus('Response generated!', 'success');
                await this.synthesizeAndPlaySpeech(data.reply);
            } else {
                this.ui.updateMessage(assistantId, `Error: ${data.error}`);
                this.ui.showStatus(`Failed to generate reply: ${data.error}`, 'error');
            }
        } catch (error) {
            // Attempt to surface error in the most recent assistant bubble if present
            try {
                const lastAssistant = Array.from(this.ui.messagesList.querySelectorAll('.message-wrapper.assistant-message')).pop();
                if (lastAssistant) {
                    this.ui.updateMessage(lastAssistant.id, `Error: ${error.message}`);
                }
            } catch {}
            this.ui.showStatus(error.message, 'error');
        } finally {
            this.pending = false;
            this.ui.sendBtn.disabled = false;
            this.ui.micBtn.disabled = false;
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
                this.ui.showStatus('Playing response...', 'success');
                this.playAudio(data.audio, data.sample_rate);
            } else {
                this.ui.showStatus(`TTS failed: ${data.error}`, 'error');
            }
        } catch (error) {
            this.ui.showStatus(`Speech synthesis error: ${error.message}`, 'error');
        }
    }

    playAudio(audioBase64, sampleRate) {
        try {
            console.log('playAudio called, audio length:', audioBase64.length);
            
            const binaryString = atob(audioBase64);
            const bytes = new Uint8Array(binaryString.length);
            for (let i = 0; i < binaryString.length; i++) {
                bytes[i] = binaryString.charCodeAt(i);
            }

            console.log('Audio bytes created, length:', bytes.length);

            const blob = new Blob([bytes], { type: 'audio/mpeg' });
            const url = URL.createObjectURL(blob);

            console.log('Blob URL created:', url);

            this.audioPlayer.src = url;
            
            // Resume audio context before playing (browser autoplay policy)
            if (this.visualizer.audioContext && this.visualizer.audioContext.state === 'suspended') {
                this.visualizer.audioContext.resume().then(() => {
                    console.log('AudioContext resumed for playback');
                    this.audioPlayer.play().then(() => {
                        console.log('Audio playback started');
                    }).catch(err => {
                        console.error('Play error:', err);
                        this.ui.showStatus(`Error playing audio: ${err.message}`, 'error');
                    });
                });
            } else {
                this.audioPlayer.play().then(() => {
                    console.log('Audio playback started');
                }).catch(err => {
                    console.error('Play error:', err);
                    this.ui.showStatus(`Error playing audio: ${err.message}`, 'error');
                });
            }

            // Clean up the URL after the audio loads
            this.audioPlayer.onloadeddata = () => {
                console.log('Audio loaded successfully');
                URL.revokeObjectURL(url);
            };
            
            this.audioPlayer.onerror = (e) => {
                console.error('Audio element error:', e);
                this.ui.showStatus('Audio playback error', 'error');
            };
        } catch (error) {
            console.error('Audio playback error:', error);
            this.ui.showStatus(`Audio playback error: ${error.message}`, 'error');
        }
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.app = new VTCApp();
});