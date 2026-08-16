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
  type NodeMouseHandler,
  type NodeProps,
  type OnConnectEnd,
  type OnConnectStart,
  type OnNodeDrag,
  type XYPosition,
} from '@xyflow/react';
import {
  useCallback,
  useEffect,
  memo,
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
const MAX_DRAFT_PARENTS = 8;
const FIT_VIEW_OPTIONS = { padding: 0.24, maxZoom: 1 } as const;
const DEFAULT_EDGE_OPTIONS = { zIndex: 0 } as const;
const CONNECTION_LINE_STYLE = { stroke: '#2f6bff', strokeWidth: 1.8 } as const;

const ConversationNode = memo(function ConversationNode({ data, selected }: NodeProps<CanvasNode>) {
  const { record } = data;
  const draft = record.local_message_count === 0 && record.kind === 'conversation';
  const parentCount = record.parent_ids?.length || 0;
  const canReceiveParent = draft && parentCount < MAX_DRAFT_PARENTS;
  const draftLabel = parentCount === 0 ? 'Draft' : parentCount === 1 ? 'Branch' : `Merge · ${parentCount}`;

  return (
    <div className={`conversation-node ${selected ? 'is-selected' : ''} ${draft ? 'is-draft' : ''}`}>
      <Handle
        className={`node-handle node-handle-target ${canReceiveParent ? '' : 'is-disabled'}`}
        type="target"
        position={Position.Left}
        isConnectable={canReceiveParent}
        isConnectableStart={false}
        isConnectableEnd={canReceiveParent}
        aria-label={canReceiveParent ? `Attach a parent (${parentCount} of ${MAX_DRAFT_PARENTS})` : undefined}
        title={canReceiveParent ? `Attach a parent (${parentCount}/${MAX_DRAFT_PARENTS})` : undefined}
      />
      <div className="node-topline">
        <span className="node-id">{record.id}</span>
        {draft && <span className="draft-label">{draftLabel}</span>}
        {record.kind === 'merge' && <span className="kind-label">Merge</span>}
      </div>
      <div className="node-title">{record.title}</div>
      <div className="node-meta">
        {draft
          ? parentCount === 0
            ? 'No parents · no conversation'
            : `${parentCount} parent${parentCount === 1 ? '' : 's'} · not submitted`
          : `${record.message_count} message${record.message_count === 1 ? '' : 's'}`}
      </div>
      <Handle
        className="node-handle node-handle-source"
        type="source"
        position={Position.Right}
        isConnectable
        isConnectableStart
        isConnectableEnd={false}
        aria-label="Drag to create a child branch"
        title="Drag to create a child branch"
      />
    </div>
  );
});

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
  const [connectingFrom, setConnectingFrom] = useState<string | null>(null);
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
          className: targetIsDraft ? `draft-edge edge-${edge.type}` : `edge-${edge.type}`,
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

  const connectExisting = useCallback(
    async (sourceId: string, targetId: string) => {
      setBusy(true);
      setError(null);
      try {
        await callBridge('add_draft_parent', targetId, sourceId);
        await refresh();
      } catch (reason) {
        setError((reason as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [refresh],
  );

  const canConnectNodes = useCallback(
    (sourceId: string, targetId: string) => {
      if (sourceId === targetId) return false;
      const source = snapshot?.nodes?.find((node) => node.id === sourceId);
      const target = snapshot?.nodes?.find((node) => node.id === targetId);
      const targetDraft = Boolean(
        target && target.local_message_count === 0 && target.kind === 'conversation',
      );
      const parentIds = target?.parent_ids || [];
      return Boolean(source) && targetDraft && parentIds.length < MAX_DRAFT_PARENTS && !parentIds.includes(sourceId);
    },
    [snapshot],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      setConnectingFrom(null);
      if (!connection.source || !connection.target) return;
      void connectExisting(connection.source, connection.target);
    },
    [connectExisting],
  );

  const onConnectStart = useCallback<OnConnectStart>((_, connection) => {
    if (connection.handleType === 'source') {
      setConnectingFrom(connection.nodeId || null);
    }
  }, []);

  const onConnectEnd = useCallback<OnConnectEnd>(
    (event, connectionState: FinalConnectionState) => {
      setConnectingFrom(null);
      if (
        connectionState.isValid ||
        !connectionState.fromNode ||
        connectionState.fromHandle?.type !== 'source'
      ) {
        return;
      }
      const pointer = 'changedTouches' in event ? event.changedTouches[0] : event;
      const dropPosition = reactFlow.screenToFlowPosition({
        x: pointer.clientX,
        y: pointer.clientY,
      });
      const targetNode =
        connectionState.toNode ||
        [...reactFlow.getNodes()].reverse().find((node) => {
          const width = node.measured?.width || node.width || 246;
          const height = node.measured?.height || node.height || 112;
          return (
            dropPosition.x >= node.position.x &&
            dropPosition.x <= node.position.x + width &&
            dropPosition.y >= node.position.y &&
            dropPosition.y <= node.position.y + height
          );
        });
      if (targetNode) {
        if (canConnectNodes(connectionState.fromNode.id, targetNode.id)) {
          void connectExisting(connectionState.fromNode.id, targetNode.id);
        } else {
          const target = snapshot?.nodes?.find((node) => node.id === targetNode.id);
          if (target?.parent_ids?.includes(connectionState.fromNode.id)) {
            setError('That node is already a parent of this Draft.');
          } else if ((target?.parent_ids?.length || 0) >= MAX_DRAFT_PARENTS) {
            setError(`A Draft can have at most ${MAX_DRAFT_PARENTS} parents.`);
          } else {
            setError('This node has started a conversation, so its parents are locked.');
          }
        }
        return;
      }
      void branchAt(connectionState.fromNode.id, dropPosition);
    },
    [branchAt, canConnectNodes, connectExisting, reactFlow, snapshot],
  );

  const isValidConnection = useCallback(
    (connection: Edge | Connection) => {
      if (!connection.source || !connection.target) return false;
      return canConnectNodes(connection.source, connection.target);
    },
    [canConnectNodes],
  );

  const onNodeClick = useCallback<NodeMouseHandler<CanvasNode>>(
    (_, node) => setSelectedId(node.id),
    [],
  );

  const onPaneClick = useCallback(() => setSelectedId(null), []);

  const onNodeDragStop = useCallback<OnNodeDrag<CanvasNode>>(
    (_, dragged) => {
      const next = nodes.map((node) => (node.id === dragged.id ? dragged : node));
      void saveUiState(next).catch((reason: Error) => setError(reason.message));
    },
    [nodes, saveUiState],
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
      let animationFrame = 0;
      let pendingRatio = splitRatio;
      const ratioFromPointer = (pointer: PointerEvent) =>
        Math.min(0.78, Math.max(0.3, (pointer.clientX - bounds.left) / bounds.width));
      const move = (pointer: PointerEvent) => {
        pendingRatio = ratioFromPointer(pointer);
        if (animationFrame) return;
        animationFrame = window.requestAnimationFrame(() => {
          animationFrame = 0;
          setSplitRatio(pendingRatio);
        });
      };
      const stop = (pointer: PointerEvent) => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', stop);
        if (animationFrame) window.cancelAnimationFrame(animationFrame);
        const ratio = ratioFromPointer(pointer);
        setSplitRatio(ratio);
        void saveUiState(nodes, ratio).catch((reason: Error) => setError(reason.message));
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', stop);
    },
    [nodes, saveUiState, splitRatio],
  );

  const selectedRecord = useMemo(
    () => snapshot?.nodes?.find((node) => node.id === selectedId) || null,
    [selectedId, snapshot],
  );
  const selectedParents = useMemo(() => {
    const parentIds = selectedRecord?.parent_ids || [];
    const recordsById = new Map((snapshot?.nodes || []).map((node) => [node.id, node]));
    return parentIds.map((id) => recordsById.get(id)).filter((node): node is NodeRecord => Boolean(node));
  }, [selectedRecord, snapshot]);
  const selectedIsDraft = Boolean(
    selectedRecord && selectedRecord.local_message_count === 0 && selectedRecord.kind === 'conversation',
  );

  const removeParent = useCallback(
    async (parentId: string) => {
      if (!selectedId) return;
      setBusy(true);
      setError(null);
      try {
        await callBridge('remove_draft_parent', selectedId, parentId);
        await refresh();
      } catch (reason) {
        setError((reason as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [refresh, selectedId],
  );

  if (!snapshot) {
    return (
      <AppFrame platform="windows" workspaceName="">
        <CenteredState title="Opening workspace…" detail="Connecting to the local Canvas GPT service." />
      </AppFrame>
    );
  }

  if (!snapshot.initialized) {
    return <AppFrame platform={snapshot.platform} workspaceName={snapshot.workspace_name}>
        <CenteredState
          title="Create a local graph"
          detail={`Initialize Canvas GPT in “${snapshot.workspace_name}”. No API key is required for the canvas.`}
          action={<button onClick={initialize} disabled={busy}>Initialize workspace</button>}
          error={error}
        />
      </AppFrame>;
  }

  const apiReady = Boolean(snapshot.config?.api_key_configured);
  const apiEnvironment = snapshot.config?.api_key_environment || 'OPENAI_API_KEY';

  return (
    <AppFrame
      platform={snapshot.platform}
      workspaceName={snapshot.workspace_name}
      actions={
        <>
          <span className={`api-status ${apiReady ? 'is-ready' : 'is-missing'}`}>
            <span className="status-dot" />
            {apiReady ? `${snapshot.config?.provider} ready` : 'API not configured'}
          </span>
          <button className="quiet-button" onClick={newGraph} disabled={busy}>New graph</button>
        </>
      }
    >

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
          {connectingFrom && (
            <div className="connection-hint" role="status">
              Drop on a Draft node to attach it, or on empty canvas to create a branch.
            </div>
          )}
          <ReactFlow<CanvasNode, Edge>
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick}
            onPaneClick={onPaneClick}
            onNodeDragStop={onNodeDragStop}
            onConnect={onConnect}
            onConnectStart={onConnectStart}
            onConnectEnd={onConnectEnd}
            isValidConnection={isValidConnection}
            edgesReconnectable={false}
            deleteKeyCode={null}
            connectOnClick={false}
            connectionRadius={40}
            connectionLineStyle={CONNECTION_LINE_STYLE}
            fitView
            fitViewOptions={FIT_VIEW_OPTIONS}
            minZoom={0.25}
            maxZoom={1.6}
            defaultEdgeOptions={DEFAULT_EDGE_OPTIONS}
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
                  <span>
                    {selectedIsDraft
                      ? selectedParents.length === 0
                        ? 'Draft'
                        : selectedParents.length === 1
                          ? 'Branch Draft'
                          : `Merge Draft · ${selectedParents.length} parents`
                      : `${selectedRecord.message_count} messages`}
                  </span>
                </div>
              </div>

              {selectedIsDraft && (
                <section className="parent-panel" aria-label="Draft parents">
                  <div className="parent-panel-heading">
                    <span>Parents</span>
                    <span>{selectedParents.length}/{MAX_DRAFT_PARENTS}</span>
                  </div>
                  {selectedParents.length ? (
                    <div className="parent-chips">
                      {selectedParents.map((parent) => (
                        <div className="parent-chip" key={parent.id} title={`${parent.id} · ${parent.title}`}>
                          <span>{parent.title}</span>
                          <button
                            type="button"
                            onClick={() => void removeParent(parent.id)}
                            disabled={busy}
                            aria-label={`Remove ${parent.title} as parent`}
                          >×</button>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p>Drag from another node’s right port onto this node.</p>
                  )}
                </section>
              )}

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
                    <span className="empty-kicker">
                      {selectedParents.length >= 2 ? 'Merge Draft' : selectedParents.length === 1 ? 'Branch Draft' : 'Draft node'}
                    </span>
                    <h3>{selectedParents.length >= 2 ? 'Ready to synthesize.' : 'No conversation yet.'}</h3>
                    <p>
                      {selectedParents.length >= 2
                        ? 'Your first message becomes the merge instruction. Parents stay unchanged.'
                        : selectedParents.length === 1
                          ? 'Add another parent to turn this into a Merge Draft, or start this branch.'
                          : 'Rename this node, attach a parent, or start a new conversation.'}
                    </p>
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
                  placeholder={
                    apiReady
                      ? selectedIsDraft && selectedParents.length >= 2
                        ? 'Describe how to merge these contexts…'
                        : 'Continue this node…'
                      : `Set ${apiEnvironment} to start chatting`
                  }
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
    </AppFrame>
  );
}

function AppFrame({
  platform = 'windows',
  workspaceName,
  actions,
  children,
}: {
  platform?: Snapshot['platform'];
  workspaceName: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  const windowAction = useCallback((method: string) => {
    void callBridge(method).catch(() => undefined);
  }, []);

  const beginWindowResize = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>, edge: string) => {
      event.preventDefault();
      const startX = event.screenX;
      const startY = event.screenY;
      const startWidth = window.innerWidth;
      const startHeight = window.innerHeight;
      let pending: [number, number, string] | null = null;
      let sending = false;

      const flush = async () => {
        if (sending || !pending) return;
        sending = true;
        const next = pending;
        pending = null;
        try {
          await callBridge('resize_window', ...next);
        } catch {
          // Window chrome should never interrupt canvas work.
        } finally {
          sending = false;
          if (pending) void flush();
        }
      };

      const queueResize = (pointer: PointerEvent) => {
        const deltaX = pointer.screenX - startX;
        const deltaY = pointer.screenY - startY;
        const fromWest = edge.includes('west');
        const fromNorth = edge.includes('north');
        const width = edge === 'north' || edge === 'south'
          ? startWidth
          : startWidth + (fromWest ? -deltaX : deltaX);
        const height = edge === 'west' || edge === 'east'
          ? startHeight
          : startHeight + (fromNorth ? -deltaY : deltaY);
        const anchor = `${fromNorth ? 'south' : 'north'}-${fromWest ? 'east' : 'west'}`;
        pending = [Math.max(900, width), Math.max(600, height), anchor];
        void flush();
      };

      const move = (pointer: PointerEvent) => queueResize(pointer);
      const stop = (pointer: PointerEvent) => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', stop);
        queueResize(pointer);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', stop);
    },
    [],
  );

  return (
    <div className="app-shell">
      <header className={`app-header platform-${platform}`}>
        <div
          className="titlebar-identity pywebview-drag-region"
          onDoubleClick={() => windowAction('toggle_maximize_window')}
        >
          <span className="titlebar-mark" aria-hidden="true">C</span>
          <strong>Canvas GPT</strong>
          {workspaceName && <span>{workspaceName}</span>}
        </div>
        {actions && <div className="header-actions">{actions}</div>}
        <div className="window-controls" aria-label="Window controls">
          <button
            className="window-control window-minimize"
            onClick={() => windowAction('minimize_window')}
            aria-label="Minimize window"
            title="Minimize"
          ><span aria-hidden="true" /></button>
          <button
            className="window-control window-maximize"
            onClick={() => windowAction('toggle_maximize_window')}
            aria-label="Maximize or restore window"
            title="Maximize or restore"
          ><span aria-hidden="true" /></button>
          <button
            className="window-control window-close"
            onClick={() => windowAction('close_window')}
            aria-label="Close window"
            title="Close"
          ><span aria-hidden="true" /></button>
        </div>
      </header>
      {children}
      {['north', 'east', 'south', 'west', 'north-east', 'south-east', 'south-west', 'north-west'].map((edge) => (
        <div
          key={edge}
          className={`window-resize-handle resize-${edge}`}
          onPointerDown={(event) => beginWindowResize(event, edge)}
          aria-hidden="true"
        />
      ))}
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
