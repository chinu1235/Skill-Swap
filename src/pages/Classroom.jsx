import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { io } from 'socket.io-client';
import { useAuth } from '../context/AuthContext.jsx';
import { apiRequest, getStoredToken } from '../services/api.js';
import CodeEditor from '../components/CodeEditor.jsx';
import { classroomEditorReadOnly, shouldApplyEditorSnapshot } from '../components/editorLanguages.js';
import './Classroom.css';

const API_URL = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:5000').replace(/\/+$/, '');

export default function Classroom() {
  const { bookingId } = useParams();
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [code, setCode] = useState('');
  const [language, setLanguage] = useState('javascript');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [cameraOn, setCameraOn] = useState(true);
  const [microphoneOn, setMicrophoneOn] = useState(true);
  const [participantPresent, setParticipantPresent] = useState(false);
  const [callState, setCallState] = useState('Not connected');
  const [localStream, setLocalStream] = useState(null);
  const [remoteStream, setRemoteStream] = useState(null);
  const [inCall, setInCall] = useState(false);
  const [callEnabled, setCallEnabled] = useState(true);
  const [executionRunning, setExecutionRunning] = useState(false);
  const [executionOutput, setExecutionOutput] = useState(null);
  const socketRef = useRef(null);
  const localVideoRef = useRef(null);
  const remoteVideoRef = useRef(null);
  const lastSentRef = useRef({ code: '', language: 'javascript' });
  const editorRevisionRef = useRef(0);
  const editorInitializedRef = useRef(false);
  const latestRunRef = useRef('');

  const loadClassroom = useCallback(async () => {
    try {
      const result = await apiRequest(`/api/bookings/${bookingId}/classroom`, { auth: true });
      setData(result);
      const revision = result.editor?.revision || 0;
      if (shouldApplyEditorSnapshot(revision, editorRevisionRef.current, editorInitializedRef.current)) {
        const initialCode = result.editor?.code || '';
        const initialLanguage = result.editor?.language || 'javascript';
        setCode(initialCode);
        setLanguage(initialLanguage);
        lastSentRef.current = { code: initialCode, language: initialLanguage };
        editorRevisionRef.current = revision;
        editorInitializedRef.current = true;
      }
      setMessage('');
    } catch (error) {
      setMessage(error.message);
    }
  }, [bookingId]);

  useEffect(() => { loadClassroom(); }, [loadClassroom]);

  useEffect(() => {
    if (!['not_started', 'in_progress'].includes(data?.session?.state)) return undefined;
    const poll = window.setInterval(loadClassroom, 5000);
    return () => window.clearInterval(poll);
  }, [data?.session?.state, loadClassroom]);

  useEffect(() => {
    if (localVideoRef.current) localVideoRef.current.srcObject = localStream;
  }, [localStream]);
  useEffect(() => {
    if (remoteVideoRef.current) remoteVideoRef.current.srcObject = remoteStream;
  }, [remoteStream]);

  useEffect(() => {
    if (data?.session?.state !== 'in_progress' || !callEnabled) return undefined;
    let active = true;
    let peer = null;
    let local = null;
    let socket = null;
    let makingOffer = false;
    let mediaReady = false;
    let participantJoined = false;
    let pendingIceCandidates = [];
    let resolveMediaReady;
    const mediaReadyPromise = new Promise((resolve) => { resolveMediaReady = resolve; });
    const rtcConfig = { iceServers: data.iceServers || [] };

    const start = () => {
      const ensurePeer = () => {
        if (!peer) {
          peer = new RTCPeerConnection(rtcConfig);
          peer.ontrack = (event) => setRemoteStream(event.streams[0] || null);
          peer.onicecandidate = (event) => {
            if (event.candidate) socket?.emit('webrtc:signal', { bookingId, kind: 'ice-candidate', data: event.candidate.toJSON() });
          };
          peer.onconnectionstatechange = () => {
            const state = peer?.connectionState || 'Not connected';
            setCallState(state);
            if (state === 'connected' && local?.getTracks().some((track) => track.readyState === 'live')) {
              socket?.emit('webrtc:connected', { bookingId });
            }
          };
        }
        const senders = new Set(peer.getSenders().map((sender) => sender.track?.id).filter(Boolean));
        local?.getTracks().forEach((track) => { if (!senders.has(track.id)) peer.addTrack(track, local); });
        return peer;
      };

      const createTeacherOffer = () => {
        if (!mediaReady || !local?.getTracks().some((track) => track.readyState === 'live') || !participantJoined || user?.role !== 'teacher' || makingOffer) return;
        makingOffer = true;
        const connection = ensurePeer();
        connection.createOffer().then((offer) => connection.setLocalDescription(offer)).then(() => {
          socket?.emit('webrtc:signal', { bookingId, kind: 'offer', data: connection.localDescription.toJSON() });
        }).catch(() => setMessage('Could not create the video call offer.')).finally(() => { makingOffer = false; });
      };

      socket = io(`${API_URL}/classroom`, { auth: { token: getStoredToken() }, transports: ['websocket', 'polling'] });
      socketRef.current = socket;
      socket.on('connect', () => {
        setCallState('Joining classroom');
        socket.emit('classroom:join', { bookingId }, (result) => {
          if (!result?.ok) { setInCall(false); setMessage(result?.error || 'Could not join classroom'); }
          else setInCall(true);
        });
      });
      socket.on('disconnect', () => setInCall(false));
      socket.on('classroom:session_ended', (event) => {
        if (event?.bookingId !== bookingId) return;
        setData((current) => current ? { ...current, booking: { ...current.booking, status: 'completed' }, session: { ...current.session, state: 'completed' }, canEnd: false } : current);
        setMessage('The teacher has ended this session.');
      });
      socket.on('connect_error', () => setMessage('Could not connect to classroom signalling. Check the server and network configuration.'));
      socket.on('classroom:participant', (event) => {
        participantJoined = event.state === 'joined';
        setParticipantPresent(event.state === 'joined');
        if (event.state === 'joined') createTeacherOffer();
        if (event.state === 'left') {
          peer?.close(); peer = null; setRemoteStream(null); setCallState('Participant left');
        }
      });
      socket.on('webrtc:signal', async ({ kind, data: signal }) => {
        try {
          if (kind === 'ice-candidate') {
            if (peer?.remoteDescription) await peer.addIceCandidate(signal);
            else pendingIceCandidates.push(signal);
            return;
          }
          await mediaReadyPromise;
          if (!active) return;
          const connection = ensurePeer();
          if (kind === 'offer' && user?.role !== 'teacher') {
            await connection.setRemoteDescription(signal);
            for (const candidate of pendingIceCandidates) await connection.addIceCandidate(candidate);
            pendingIceCandidates = [];
            const answer = await connection.createAnswer();
            await connection.setLocalDescription(answer);
            socket.emit('webrtc:signal', { bookingId, kind: 'answer', data: connection.localDescription.toJSON() });
          } else if (kind === 'answer' && user?.role === 'teacher') {
            await connection.setRemoteDescription(signal);
            for (const candidate of pendingIceCandidates) await connection.addIceCandidate(candidate);
            pendingIceCandidates = [];
          }
        } catch { setMessage('The video connection could not be negotiated.'); }
      });
      socket.on('classroom:editor-sync', (editor) => {
        const revision = editor.revision || 0;
        if (!shouldApplyEditorSnapshot(revision, editorRevisionRef.current, editorInitializedRef.current)) return;
        editorRevisionRef.current = revision;
        editorInitializedRef.current = true;
        lastSentRef.current = { code: editor.code || '', language: editor.language || 'javascript' };
        setCode(editor.code || ''); setLanguage(editor.language || 'javascript');
      });
      socket.on('editor:update', (editor) => {
        if (!shouldApplyEditorSnapshot(editor.revision || 0, editorRevisionRef.current, true)) return;
        editorRevisionRef.current = editor.revision;
        lastSentRef.current = { code: editor.code, language: editor.language };
        setCode(editor.code); setLanguage(editor.language);
      });
      socket.on('execution:result', (result) => {
        if (result?.runId && result.runId >= latestRunRef.current) {
          latestRunRef.current = result.runId;
          setExecutionOutput({ status: result.status, text: result.text });
        }
      });

      // Join authenticated collaboration immediately. A camera permission
      // prompt must not leave the shared editor disconnected or read-only.
      const mediaRequest = navigator.mediaDevices?.getUserMedia
        ? navigator.mediaDevices.getUserMedia({ video: true, audio: true })
        : Promise.reject(new Error('Media capture is unavailable'));
      mediaRequest.then((stream) => {
        if (!active) { stream.getTracks().forEach((track) => track.stop()); return; }
        local = stream;
        setLocalStream(stream);
        setCameraOn(true);
        setMicrophoneOn(true);
        mediaReady = true;
        resolveMediaReady();
        createTeacherOffer();
      }).catch(() => {
        if (!active) { mediaReady = true; resolveMediaReady(); return; }
        setMessage('Camera or microphone access was unavailable. You can still use the shared editor.');
        mediaReady = true;
        resolveMediaReady();
      });
    };

    start();
    return () => {
      active = false;
      if (socket) {
        socket.emit('classroom:leave', { bookingId });
        socket.disconnect();
      }
      socketRef.current = null;
      peer?.close();
      local?.getTracks().forEach((track) => track.stop());
      setLocalStream(null); setRemoteStream(null); setInCall(false); setParticipantPresent(false);
    };
  }, [data?.session?.state, data?.iceServers, bookingId, user?.role, callEnabled]);

  const publishEditorChange = (nextCode, nextLanguage = language) => {
    setCode(nextCode); setLanguage(nextLanguage);
    if (lastSentRef.current.code === nextCode && lastSentRef.current.language === nextLanguage) return;
    lastSentRef.current = { code: nextCode, language: nextLanguage };
    socketRef.current?.emit('editor:update', { bookingId, code: nextCode, language: nextLanguage }, (result) => {
      if (result && !result.ok) setMessage(result.error || 'Could not synchronize the edit.');
      else if (result?.revision) editorRevisionRef.current = Math.max(editorRevisionRef.current, result.revision);
    });
  };

  const runCode = async () => {
    if (editorReadOnly) return;
    if (!['javascript', 'python', 'c', 'cpp'].includes(language)) {
      setExecutionOutput({ status: 'Unsupported language', text: `${language.toUpperCase()} cannot run through the configured execution service.` });
      return;
    }
    setExecutionRunning(true);
    setExecutionOutput({ status: 'Running', text: 'Submitting to the isolated execution service…' });
    try {
      const result = await apiRequest(`/api/bookings/${bookingId}/classroom/run`, { method: 'POST', auth: true, body: { code, language, stdin: '' } });
      if (result.runId >= latestRunRef.current) {
        latestRunRef.current = result.runId;
        setExecutionOutput({ status: result.status, text: result.text });
      }
    } catch (error) {
      setExecutionOutput({ status: 'Execution failed', text: error.message });
    } finally {
      setExecutionRunning(false);
    }
  };

  const toggleTrack = (kind) => {
    const tracks = localStream?.getTracks().filter((track) => track.kind === kind) || [];
    tracks.forEach((track) => { track.enabled = !track.enabled; });
    if (kind === 'video') setCameraOn(tracks.some((track) => track.enabled));
    else setMicrophoneOn(tracks.some((track) => track.enabled));
  };

  const startSession = async () => {
    setBusy(true); setMessage('');
    try { await apiRequest(`/api/bookings/${bookingId}/session/start`, { method: 'POST', auth: true, body: {} }); await loadClassroom(); }
    catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  };

  const endSession = async () => {
    if (!window.confirm('End this teaching session? Participants will see that it has ended.')) return;
    setBusy(true); setMessage('');
    try {
      await apiRequest(`/api/bookings/${bookingId}/session/end`, { method: 'POST', auth: true, body: {} });
      await loadClassroom();
      setMessage('Session has ended successfully.');
    }
    catch (error) { setMessage(error.message); await loadClassroom(); }
    finally { setBusy(false); }
  };

  const leaveCall = () => {
    setCallEnabled(false);
    socketRef.current?.emit('classroom:leave', { bookingId });
    socketRef.current?.disconnect();
    socketRef.current = null;
    localStream?.getTracks().forEach((track) => track.stop());
    setLocalStream(null); setRemoteStream(null); setInCall(false); setCallState('You left the call');
  };

  if (!data) return <section className="page-section"><div className="container"><p role="status">{message || 'Loading classroom…'}</p><Link to="/dashboard">Back to dashboard</Link></div></section>;

  const teacher = user?.role === 'teacher';
  const state = data.session.state;
  const editorReadOnly = classroomEditorReadOnly(state, inCall);
  return <section className="classroom-page"><div className="container classroom-container">
    <header className="classroom-heading"><div><span className="eyebrow">Scheduled lesson</span><h1>{data.booking.skill?.skillName || 'Teaching classroom'}</h1><p>{data.booking.bookingDate} at {data.booking.bookingTime} · {data.booking.durationMinutes} minutes</p></div><Link className="button button-outline" to="/dashboard">Back to dashboard</Link></header>
    {message && <p className="form-message classroom-message" role="status">{message}</p>}
    {state === 'review_required' && <div className="classroom-review" role="alert"><strong>Session review required</strong><span>The permitted end window passed without a recorded end. The booking remains confirmed and has not been marked completed.</span></div>}
    {state === 'completed' && <div className="classroom-review classroom-complete" role="status"><strong>Lesson completed</strong><span>The teacher recorded the session end.</span></div>}
    <div className="classroom-main-grid">
      <section className="classroom-call-card">
        <div className="classroom-participants">
          <article><video ref={remoteVideoRef} autoPlay playsInline /><strong>{teacher ? data.booking.learner?.name : data.booking.teacher?.name}</strong><span>{participantPresent ? 'In classroom' : 'Waiting for participant'}</span></article>
          <article><video ref={localVideoRef} autoPlay playsInline muted /><strong>You</strong><span>{callState}</span></article>
        </div>
        {state === 'not_started' && <p className="classroom-hint">{teacher ? 'Start the lesson during its scheduled time.' : 'The teacher will start the lesson during its scheduled time.'}</p>}
        <div className="classroom-controls">
          {teacher && data.canStart && <button className="button" type="button" disabled={busy} onClick={startSession}>{busy ? 'Starting…' : 'Start lesson'}</button>}
          {state === 'in_progress' && !inCall && <button className="button" type="button" onClick={() => setCallEnabled(true)}>Join call</button>}
          {state === 'in_progress' && inCall && <>
            <button className="button button-outline" type="button" disabled={!localStream} onClick={() => toggleTrack('video')}>{cameraOn ? 'Turn camera off' : 'Turn camera on'}</button>
            <button className="button button-outline" type="button" disabled={!localStream} onClick={() => toggleTrack('audio')}>{microphoneOn ? 'Mute microphone' : 'Unmute microphone'}</button>
            <button className="button button-outline" type="button" onClick={leaveCall}>Leave Classroom</button>
          </>}
          {teacher && ['not_started', 'in_progress'].includes(state) && <button className="button classroom-end-button" type="button" disabled={busy || state !== 'in_progress'} onClick={endSession}>{busy ? 'Ending…' : 'End Session'}</button>}
        </div>
      </section>
      <CodeEditor value={code} language={language} onChange={(value) => publishEditorChange(value)} onLanguageChange={(value) => publishEditorChange(code, value)} readOnly={editorReadOnly} running={executionRunning} sharedOutput={executionOutput} runButtonLabel="Run code" onRun={runCode} className="editor-workspace classroom-editor" />
    </div>
  </div></section>;
}
