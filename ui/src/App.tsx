import {
  Background,
  BackgroundVariant,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type FinalConnectionState,
  type Node,
  type NodeProps,
  type OnConnectEnd,
  type XYPosition,
} from '@xyflow/react';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import { callBridge } from './bridge';
import type { Conversation, NodeRecord, Snapshot } from './types';

type CanvasNodeData = {
  record: NodeRecord;
};

type CanvasNode = Node<CanvasNodeData, 'conversation'>;

const DEFAULT_SPLIT = 0.64;

function ConversationNode({ data, selected }: NodeProps<CanvasNode>) {
  const { record } = data;
  const draft = record.local_message_count === 0 && record.kind === 'conversation';
  const committed = !draft;

  return (
    <div className={`conversation-node ${selected ? 'is-selected' : ''} ${draft ? 'is-draft' : ''}`}>
      <Handle
        className={`node-handle node-handle-target ${draft ? '' : 'is-disabled'}`}
        type="target"
        position={Position.Left}
        isConnectable={draft}
      />
      <div className="node-topline">
        <span className="node-id">{record.id}</span>
        {draft && <span className="draft-label">Draft</span>}
        {record.kind === 'merge' && <span className="kind-label">Merge</span>}
      </div>
      <div className="node-title">{record.title}</div>
      <div className="node-meta">
        {record.message_count === 0
          ? 'No conversation yet'
          : `${record.message_count} message${record.message_count === 1 ? '' : 's'}`}
      </div>
      <Handle
        className={`node-handle node-handle-source ${committed ? '' : 'is-disabled'}`}
        type="source"
        position={Position.Right}
        isConnectable={committed}
      />
    </div>
  );
}

const nodeTypes = { conversation: ConversationNode };

function positionForIndex(index: number): XYPosition {
  return {
    x: 80 + (index % 3) * 310,
    y: 80 + Math.floor(index / 3) * 190,
  };
}

function CanvasWorkspace() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<CanvasNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [titleDraft, setTitleDraft] = useState('');
  const [message, setMessage] = useState('');
  const [splitRatio, setSplitRatio] = useState(DEFAULT_SPLIT);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pendingPositions = useRef<Record<string, XYPosition>>({});
  const shellRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const reactFlow = useReactFlow<CanvasNode, Edge>();

  const refresh = useCallback(async () => {
    const next = await callBridge<Snapshot>('bootstrap');
    setSnapshot(next);
    return next;
  }, []);

  useEffect(() => {
    refresh().catch((reason: Error) => setError(reason.message));
  }, [refresh]);

  useEffect(() => {
    if (!snapshot?.initialized) {
      setNodes([]);
      setEdges([]);
      return;
    }
    const records = snapshot.nodes || [];
    const savedPositions = snapshot.ui?.positions || {};
    setNodes((current) => {
      const currentById = new Map(current.map((node) => [node.id, node]));
      return records.map((record, index) => {
        const currentNode = currentById.get(record.id);
        return {
          id: record.id,
          type: 'conversation',
          position:
            pendingPositions.current[record.id] ||
            currentNode?.position ||
            savedPositions[record.id] ||
            positionForIndex(index),
          data: { record },
          selected: record.id === selectedId,
          deletable: false,
        };
      });
    });
    pendingPositions.current = {};
    const recordById = new Map(records.map((record) => [record.id, record]));
    setEdges(
      (snapshot.edges || []).map((edge, index) => {
        const target = recordById.get(edge.target);
        const targetIsDraft = target?.local_message_count === 0 && target.kind === 'conversation';
        return {
          id: `${edge.type}-${edge.source}-${edge.target}-${index}`,
          source: edge.source,
          target: edge.target,
          type: 'smoothstep',
          selectable: false,
          deletable: false,
          reconnectable: false,
          markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
          className: targetIsDraft && edge.type === 'branch' ? 'draft-edge' : `edge-${edge.type}`,
        };
      }),
    );
    if (typeof snapshot.ui?.split_ratio === 'number') {
      setSplitRatio(snapshot.ui.split_ratio);
    }
    if (selectedId && !records.some((record) => record.id === selectedId)) {
      setSelectedId(null);
    }
  }, [selectedId, setEdges, setNodes, snapshot]);

  useEffect(() => {
    if (!selectedId) {
      setConversation(null);
      setTitleDraft('');
      return;
    }
    callBridge<Conversation>('get_conversation', selectedId)
      .then((next) => {
        setConversation(next);
        setTitleDraft(next.node.title);
      })
      .catch((reason: Error) => setError(reason.message));
  }, [selectedId, snapshot]);

  const saveUiState = useCallback(
    async (nextNodes: CanvasNode[] = nodes, ratio = splitRatio) => {
      const positions = Object.fromEntries(
        nextNodes.map((node) => [node.id, { x: node.position.x, y: node.position.y }]),
      );
      await callBridge('save_ui_state', positions, ratio);
    },
    [nodes, splitRatio],
  );

  const createNode = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const record = await callBridge<NodeRecord>('create_node');
      const bounds = canvasRef.current?.getBoundingClientRect();
      const position = reactFlow.screenToFlowPosition({
        x: bounds ? bounds.left + bounds.width / 2 : window.innerWidth / 3,
        y: bounds ? bounds.top + bounds.height / 2 : window.innerHeight / 2,
      });
      pendingPositions.current[record.id] = position;
      await callBridge(
        'save_ui_state',
        {
          ...Object.fromEntries(nodes.map((node) => [node.id, node.position])),
          [record.id]: position,
        },
        splitRatio,
      );
      setSelectedId(record.id);
      await refresh();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }, [nodes, reactFlow, refresh, splitRatio]);

  const branchAt = useCallback(
    async (sourceId: string, position: XYPosition) => {
      setBusy(true);
      setError(null);
      try {
        const record = await callBridge<NodeRecord>('branch_node', sourceId);
        pendingPositions.current[record.id] = position;
        await callBridge(
          'save_ui_state',
          {
            ...Object.fromEntries(nodes.map((node) => [node.id, node.position])),
            [record.id]: position,
          },
          splitRatio,
        );
        setSelectedId(record.id);
        await refresh();
      } catch (reason) {
        setError((reason as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [nodes, refresh, splitRatio],
  );

  const onConnect = useCallback(
    async (connection: Connection) => {
      if (!connection.source || !connection.target) return;
      setBusy(true);
      setError(null);
      try {
        await callBridge('set_branch_parent', connection.target, connection.source);
        await refresh();
      } catch (reason) {
        setError((reason as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [refresh],
  );

  const onConnectEnd = useCallback<OnConnectEnd>(
    (event, connectionState: FinalConnectionState) => {
      if (connectionState.isValid || connectionState.toNode || !connectionState.fromNode) return;
      const pointer = 'changedTouches' in event ? event.changedTouches[0] : event;
      void branchAt(
        connectionState.fromNode.id,
        reactFlow.screenToFlowPosition({ x: pointer.clientX, y: pointer.clientY }),
      );
    },
    [branchAt, reactFlow],
  );

  const isValidConnection = useCallback(
    (connection: Edge | Connection) => {
      if (!connection.source || !connection.target || connection.source === connection.target) {
        return false;
      }
      const source = snapshot?.nodes?.find((node) => node.id === connection.source);
      const target = snapshot?.nodes?.find((node) => node.id === connection.target);
      const sourceCommitted = Boolean(source && (source.local_message_count > 0 || source.kind === 'merge'));
      const targetDraft = Boolean(target && target.local_message_count === 0 && target.kind === 'conversation');
      return sourceCommitted && targetDraft;
    },
    [snapshot],
  );

  const renameSelected = useCallback(async () => {
    if (!selectedId || !conversation || titleDraft.trim() === conversation.node.title) return;
    if (!titleDraft.trim()) {
      setTitleDraft(conversation.node.title);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await callBridge('rename_node', selectedId, titleDraft.trim());
      await refresh();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }, [conversation, refresh, selectedId, titleDraft]);

  const sendMessage = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      if (!selectedId || !message.trim() || !snapshot?.config?.api_key_configured) return;
      setBusy(true);
      setError(null);
      try {
        await callBridge('chat', selectedId, message.trim());
        setMessage('');
        await refresh();
      } catch (reason) {
        setError((reason as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [message, refresh, selectedId, snapshot?.config?.api_key_configured],
  );

  const initialize = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await callBridge<Snapshot>('initialize_workspace');
      setSnapshot(next);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  const newGraph = useCallback(async () => {
    if (!window.confirm('Start a new graph? The current graph will be cleared.')) return;
    setBusy(true);
    setError(null);
    try {
      const next = await callBridge<Snapshot>('new_graph');
      setSelectedId(null);
      setSnapshot(next);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  const beginResize = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      event.currentTarget.setPointerCapture(event.pointerId);
      const shell = shellRef.current;
      if (!shell) return;
      const bounds = shell.getBoundingClientRect();
      const move = (pointer: PointerEvent) => {
        const ratio = Math.min(0.78, Math.max(0.3, (pointer.clientX - bounds.left) / bounds.width));
        setSplitRatio(ratio);
      };
      const stop = (pointer: PointerEvent) => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', stop);
        const ratio = Math.min(0.78, Math.max(0.3, (pointer.clientX - bounds.left) / bounds.width));
        setSplitRatio(ratio);
        void saveUiState(nodes, ratio).catch((reason: Error) => setError(reason.message));
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', stop);
    },
    [nodes, saveUiState],
  );

  const selectedRecord = useMemo(
    () => snapshot?.nodes?.find((node) => node.id === selectedId) || null,
    [selectedId, snapshot],
  );

  if (!snapshot) {
    return <CenteredState title="Opening workspace…" detail="Connecting to the local Canvas GPT service." />;
  }

  if (!snapshot.initialized) {
    return (
      <CenteredState
        title="Create a local graph"
        detail={`Initialize Canvas GPT in “${snapshot.workspace_name}”. No API key is required for the canvas.`}
        action={<button onClick={initialize} disabled={busy}>Initialize workspace</button>}
        error={error}
      />
    );
  }

  const apiReady = Boolean(snapshot.config?.api_key_configured);
  const apiEnvironment = snapshot.config?.api_key_environment || 'OPENAI_API_KEY';

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">C</span>
          <div>
            <strong>Canvas GPT</strong>
            <span>{snapshot.workspace_name}</span>
          </div>
        </div>
        <div className="header-actions">
          <span className={`api-status ${apiReady ? 'is-ready' : 'is-missing'}`}>
            <span className="status-dot" />
            {apiReady ? `${snapshot.config?.provider} ready` : 'API not configured'}
          </span>
          <button className="quiet-button" onClick={newGraph} disabled={busy}>New graph</button>
        </div>
      </header>

      <div className="split-shell" ref={shellRef}>
        <section className="canvas-pane" style={{ flexBasis: `${splitRatio * 100}%` }} ref={canvasRef}>
          <div className="canvas-toolbar">
            <button className="primary-button" onClick={createNode} disabled={busy}>+ Node</button>
            <button className="icon-button" onClick={() => reactFlow.fitView({ padding: 0.24 })}>Fit</button>
            <button className="icon-button" onClick={() => reactFlow.zoomOut()}>−</button>
            <button className="icon-button" onClick={() => reactFlow.zoomIn()}>+</button>
          </div>
          {nodes.length === 0 && (
            <div className="canvas-empty">
              <span className="empty-kicker">Empty graph</span>
              <h2>Start with one thought.</h2>
              <p>Create a node, then name it or connect an API to begin the conversation.</p>
              <button className="primary-button" onClick={createNode} disabled={busy}>Create first node</button>
            </div>
          )}
          <ReactFlow<CanvasNode, Edge>
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={(_, node) => setSelectedId(node.id)}
            onPaneClick={() => setSelectedId(null)}
            onNodeDragStop={(_, dragged) => {
              const next = nodes.map((node) => (node.id === dragged.id ? dragged : node));
              void saveUiState(next).catch((reason: Error) => setError(reason.message));
            }}
            onConnect={onConnect}
            onConnectEnd={onConnectEnd}
            isValidConnection={isValidConnection}
            edgesReconnectable={false}
            deleteKeyCode={null}
            connectOnClick={false}
            fitView
            fitViewOptions={{ padding: 0.24, maxZoom: 1 }}
            minZoom={0.25}
            maxZoom={1.6}
            defaultEdgeOptions={{ zIndex: 0 }}
          >
            <Background variant={BackgroundVariant.Dots} gap={24} size={1.2} />
          </ReactFlow>
        </section>

        <div
          className="splitter"
          role="separator"
          aria-label="Resize canvas and conversation"
          aria-orientation="vertical"
          onPointerDown={beginResize}
          onDoubleClick={() => {
            setSplitRatio(DEFAULT_SPLIT);
            void saveUiState(nodes, DEFAULT_SPLIT).catch((reason: Error) => setError(reason.message));
          }}
        />

        <aside className="conversation-pane">
          {!selectedRecord ? (
            <div className="conversation-empty">
              <span className="selection-glyph" aria-hidden="true">↖</span>
              <h2>Select a node</h2>
              <p>Its inherited context and local conversation will appear here.</p>
            </div>
          ) : (
            <>
              <div className="conversation-header">
                <input
                  className="title-input"
                  value={titleDraft}
                  aria-label="Node title"
                  onChange={(event) => setTitleDraft(event.target.value)}
                  onBlur={() => void renameSelected()}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') event.currentTarget.blur();
                    if (event.key === 'Escape') {
                      setTitleDraft(conversation?.node.title || '');
                      event.currentTarget.blur();
                    }
                  }}
                />
                <div className="conversation-meta">
                  <span>{selectedRecord.id}</span>
                  <span>{selectedRecord.local_message_count === 0 ? 'Draft' : `${selectedRecord.message_count} messages`}</span>
                </div>
              </div>

              <div className="message-list">
                {conversation?.messages.length ? (
                  conversation.messages.map((item, index) => (
                    <article className={`message message-${item.role}`} key={`${item.role}-${index}`}>
                      <span>{item.role === 'assistant' ? 'Canvas GPT' : 'You'}</span>
                      <p>{item.content}</p>
                    </article>
                  ))
                ) : (
                  <div className="draft-intro">
                    <span className="empty-kicker">Draft node</span>
                    <h3>No conversation yet.</h3>
                    <p>You can rename this node, or attach a parent by dragging from a committed node.</p>
                  </div>
                )}
              </div>

              {!apiReady && (
                <div className="api-notice">
                  <div>
                    <strong>API key not configured</strong>
                    <p>The canvas works offline. Chat stays disabled until the app is relaunched with this environment variable.</p>
                  </div>
                  <code>{apiEnvironment}</code>
                </div>
              )}

              <form className="composer" onSubmit={sendMessage}>
                <textarea
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  disabled={!apiReady || busy}
                  placeholder={apiReady ? 'Continue this node…' : `Set ${apiEnvironment} to start chatting`}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault();
                      event.currentTarget.form?.requestSubmit();
                    }
                  }}
                />
                <button className="send-button" disabled={!apiReady || busy || !message.trim()} aria-label="Send message">↑</button>
              </form>
            </>
          )}
        </aside>
      </div>

      {error && (
        <div className="error-toast" role="alert">
          <span>{error}</span>
          <button onClick={() => setError(null)} aria-label="Dismiss">×</button>
        </div>
      )}
    </div>
  );
}

function CenteredState({
  title,
  detail,
  action,
  error,
}: {
  title: string;
  detail: string;
  action?: React.ReactNode;
  error?: string | null;
}) {
  return (
    <main className="centered-state">
      <span className="centered-mark">C</span>
      <h1>{title}</h1>
      <p>{detail}</p>
      {action}
      {error && <div className="inline-error">{error}</div>}
    </main>
  );
}

export default function App() {
  return (
    <ReactFlowProvider>
      <CanvasWorkspace />
    </ReactFlowProvider>
  );
}
