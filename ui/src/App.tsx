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
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import { callBridge } from './bridge';
import type { Conversation, EdgeRecord, NodeRecord, Snapshot } from './types';

type CanvasNodeData = {
  record: NodeRecord;
};

type CanvasNode = Node<CanvasNodeData, 'conversation'>;

type CanvasEdgeData = {
  record: EdgeRecord;
};

type CanvasEdge = Edge<CanvasEdgeData>;

type ContextMenuState =
  | { kind: 'node'; nodeId: string; x: number; y: number }
  | { kind: 'edge'; record: EdgeRecord; x: number; y: number };

const DEFAULT_SPLIT = 0.64;
const MAX_DRAFT_PARENTS = 8;
const MAX_NODE_CHILDREN = 50;
const FIT_VIEW_OPTIONS = { padding: 0.24, maxZoom: 1 } as const;
const DEFAULT_EDGE_OPTIONS = { zIndex: 0 } as const;
const CONNECTION_LINE_STYLE = { stroke: '#2f6bff', strokeWidth: 1.8 } as const;

const ConversationNode = memo(function ConversationNode({ data, selected }: NodeProps<CanvasNode>) {
  const { record } = data;
  const draft = record.local_message_count === 0 && record.kind === 'conversation';
  const frozen = Boolean(record.frozen);
  const parentCount = record.parent_ids?.length || 0;
  const childCount = record.child_count || 0;
  const atChildLimit = childCount >= (record.max_children || MAX_NODE_CHILDREN);
  const canCreateChild = !draft;
  const draftLabel = parentCount === 0 ? 'Draft' : parentCount === 1 ? 'Branch' : `Merge · ${parentCount}`;

  return (
    <div className={`conversation-node ${selected ? 'is-selected' : ''} ${draft ? 'is-draft' : frozen ? 'is-frozen' : 'is-active'}`}>
      <Handle
        className={`node-handle node-handle-target ${draft && parentCount >= MAX_DRAFT_PARENTS ? 'is-limit' : ''}`}
        type="target"
        position={Position.Left}
        isConnectable
        isConnectableStart={false}
        isConnectableEnd
        aria-label={draft ? `Add a context source (${parentCount} of ${MAX_DRAFT_PARENTS})` : 'Create a continuation with added context'}
        title={draft ? `Add context source (${parentCount}/${MAX_DRAFT_PARENTS})` : 'Create Merge Draft'}
      />
      <div className="node-topline">
        <span className="node-id">{record.id}</span>
        {draft && <span className="draft-label">{draftLabel}</span>}
        {record.kind === 'merge' && <span className="kind-label">Merge</span>}
        {frozen && (
          <span className="node-lock" aria-label="Discussion is frozen" title={`Frozen after branching · ${childCount}/${record.max_children || MAX_NODE_CHILDREN} children`}>
            <span aria-hidden="true" />
          </span>
        )}
      </div>
      <div className="node-title">{record.title}</div>
      <div className="node-meta">
        {draft
          ? parentCount === 0
            ? 'No parents · no conversation'
            : `${parentCount} parent${parentCount === 1 ? '' : 's'} · not submitted`
          : frozen
            ? `${record.message_count} messages · ${childCount}/${record.max_children || MAX_NODE_CHILDREN} children`
            : `${record.message_count} messages · active`}
      </div>
      <Handle
        className={`node-handle node-handle-source ${!canCreateChild ? 'is-disabled' : atChildLimit ? 'is-limit' : ''}`}
        type="source"
        position={Position.Right}
        isConnectable={canCreateChild}
        isConnectableStart={canCreateChild}
        isConnectableEnd={false}
        aria-label={draft ? 'Drafts cannot have children' : `Create child (${childCount} of ${record.max_children || MAX_NODE_CHILDREN})`}
        title={draft ? 'Send the first message before branching' : `Create child (${childCount}/${record.max_children || MAX_NODE_CHILDREN})`}
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
  const [edges, setEdges, onEdgesChange] = useEdgesState<CanvasEdge>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [titleDraft, setTitleDraft] = useState('');
  const [message, setMessage] = useState('');
  const [splitRatio, setSplitRatio] = useState(DEFAULT_SPLIT);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connectingFrom, setConnectingFrom] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [renameTargetId, setRenameTargetId] = useState<string | null>(null);
  const pendingPositions = useRef<Record<string, XYPosition>>({});
  const shellRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const titleInputRef = useRef<HTMLInputElement>(null);
  const providerMenuRef = useRef<HTMLDetailsElement>(null);
  const reactFlow = useReactFlow<CanvasNode, CanvasEdge>();

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
          interactionWidth: 24,
          data: { record: edge },
          className: [
            `edge-${edge.type}`,
            targetIsDraft ? 'draft-edge' : '',
            edge.deletable ? 'is-deletable' : 'is-locked',
          ].filter(Boolean).join(' '),
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

  useEffect(() => {
    if (!renameTargetId || renameTargetId !== selectedId || conversation?.node.id !== selectedId) return;
    titleInputRef.current?.focus();
    titleInputRef.current?.select();
    setRenameTargetId(null);
  }, [conversation, renameTargetId, selectedId]);

  useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
    };
    window.addEventListener('blur', close);
    window.addEventListener('resize', close);
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      window.removeEventListener('blur', close);
      window.removeEventListener('resize', close);
      document.removeEventListener('pointerdown', close);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [contextMenu]);

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
        const targetRecord = snapshot?.nodes?.find((node) => node.id === targetId);
        const targetIsDraft = Boolean(
          targetRecord
          && targetRecord.local_message_count === 0
          && targetRecord.kind === 'conversation',
        );
        if (targetIsDraft) {
          await callBridge('attach_parent', targetId, sourceId);
        } else {
          const record = await callBridge<NodeRecord>('create_merge_draft', [targetId, sourceId]);
          const sourceNode = reactFlow.getNode(sourceId);
          const targetNode = reactFlow.getNode(targetId);
          const position = {
            x: Math.max(sourceNode?.position.x || 0, targetNode?.position.x || 0) + 310,
            y: ((sourceNode?.position.y || 0) + (targetNode?.position.y || 0)) / 2,
          };
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
        }
        await refresh();
      } catch (reason) {
        setError((reason as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [nodes, reactFlow, refresh, snapshot, splitRatio],
  );

  const hasStructuralPath = useCallback(
    (startId: string, targetId: string) => {
      const pending = [startId];
      const visited = new Set<string>();
      while (pending.length) {
        const current = pending.pop()!;
        if (current === targetId) return true;
        if (visited.has(current)) continue;
        visited.add(current);
        for (const edge of snapshot?.edges || []) {
          if (
            edge.source === current
            && (edge.type === 'branch' || edge.type === 'merge')
          ) {
            pending.push(edge.target);
          }
        }
      }
      return false;
    },
    [snapshot],
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
      if (!source || !target) return false;
      if (source.local_message_count === 0) return false;
      if ((source.child_count || 0) >= (source.max_children || MAX_NODE_CHILDREN)) return false;
      if (targetDraft) {
        return parentIds.length < MAX_DRAFT_PARENTS
          && !parentIds.includes(sourceId)
          && !hasStructuralPath(targetId, sourceId);
      }
      return (target.child_count || 0) < (target.max_children || MAX_NODE_CHILDREN);
    },
    [hasStructuralPath, snapshot],
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
          const source = snapshot?.nodes?.find(
            (node) => node.id === connectionState.fromNode?.id,
          );
          const target = snapshot?.nodes?.find((node) => node.id === targetNode.id);
          if (source?.local_message_count === 0) {
            setError('Drafts cannot have children. Send the first message before branching.');
          } else if (
            (source?.child_count || 0) >= (source?.max_children || MAX_NODE_CHILDREN)
          ) {
            setError(`This discussion already has the maximum of ${source?.max_children || MAX_NODE_CHILDREN} children. Continue from another node or consolidate related branches.`);
          } else if (
            target?.local_message_count === 0
            && target.kind === 'conversation'
            && target.parent_ids?.includes(connectionState.fromNode.id)
          ) {
            setError('That node is already attached as a parent.');
          } else if (
            target?.local_message_count === 0
            && target.kind === 'conversation'
            && (target.parent_ids?.length || 0) >= MAX_DRAFT_PARENTS
          ) {
            setError(`A Draft can have at most ${MAX_DRAFT_PARENTS} parents.`);
          } else if (
            target?.local_message_count === 0
            && target.kind === 'conversation'
            && hasStructuralPath(targetNode.id, connectionState.fromNode.id)
          ) {
            setError('That connection would create a context cycle.');
          } else if (
            target?.local_message_count !== 0
            && (target?.child_count || 0) >= (target?.max_children || MAX_NODE_CHILDREN)
          ) {
            setError(`That discussion already has the maximum of ${target?.max_children || MAX_NODE_CHILDREN} children, so it cannot seed another Merge Draft.`);
          } else {
            setError('That connection is not allowed.');
          }
        }
        return;
      }
      void branchAt(connectionState.fromNode.id, dropPosition);
    },
    [branchAt, canConnectNodes, connectExisting, hasStructuralPath, reactFlow, snapshot],
  );

  const isValidConnection = useCallback(
    (connection: CanvasEdge | Connection) => {
      if (!connection.source || !connection.target) return false;
      return canConnectNodes(connection.source, connection.target);
    },
    [canConnectNodes],
  );

  const onNodeClick = useCallback<NodeMouseHandler<CanvasNode>>(
    (_, node) => {
      setContextMenu(null);
      setSelectedId(node.id);
    },
    [],
  );

  const onPaneClick = useCallback(() => {
    setContextMenu(null);
    setSelectedId(null);
  }, []);

  const onNodeContextMenu = useCallback(
    (event: ReactMouseEvent, node: CanvasNode) => {
      event.preventDefault();
      setSelectedId(node.id);
      setContextMenu({
        kind: 'node',
        nodeId: node.id,
        x: Math.min(event.clientX, window.innerWidth - 212),
        y: Math.min(event.clientY, window.innerHeight - 116),
      });
    },
    [],
  );

  const onEdgeContextMenu = useCallback(
    (event: ReactMouseEvent, edge: CanvasEdge) => {
      event.preventDefault();
      if (!edge.data?.record) return;
      setContextMenu({
        kind: 'edge',
        record: edge.data.record,
        x: Math.min(event.clientX, window.innerWidth - 228),
        y: Math.min(event.clientY, window.innerHeight - 84),
      });
    },
    [],
  );

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

  const renameFromMenu = useCallback((nodeId: string) => {
    setContextMenu(null);
    setSelectedId(nodeId);
    setRenameTargetId(nodeId);
  }, []);

  const deleteNode = useCallback(
    async (nodeId: string) => {
      setContextMenu(null);
      setBusy(true);
      setError(null);
      try {
        await callBridge('delete_node', nodeId);
        if (selectedId === nodeId) setSelectedId(null);
        await refresh();
      } catch (reason) {
        setError((reason as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [refresh, selectedId],
  );

  const deleteEdge = useCallback(
    async (record: EdgeRecord) => {
      setContextMenu(null);
      setBusy(true);
      setError(null);
      try {
        await callBridge('delete_edge', record.source, record.target, record.type);
        await refresh();
      } catch (reason) {
        setError((reason as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [refresh],
  );

  const sendMessage = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      if (!selectedId || !message.trim() || !snapshot?.config?.api_key_configured) return;
      const selected = snapshot.nodes?.find((node) => node.id === selectedId);
      if (selected?.frozen) {
        setError('This discussion is frozen because it has children. Create a branch to continue.');
        return;
      }
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
    [message, refresh, selectedId, snapshot],
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

  const switchProvider = useCallback(async (providerId: string) => {
    setBusy(true);
    setError(null);
    try {
      const next = await callBridge<Snapshot>('update_provider', providerId);
      setSnapshot(next);
      providerMenuRef.current?.removeAttribute('open');
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
  const contextMenuNode = useMemo(
    () => contextMenu?.kind === 'node'
      ? snapshot?.nodes?.find((node) => node.id === contextMenu.nodeId) || null
      : null,
    [contextMenu, snapshot],
  );
  const selectedParents = useMemo(() => {
    const parentIds = selectedRecord?.parent_ids || [];
    const recordsById = new Map((snapshot?.nodes || []).map((node) => [node.id, node]));
    return parentIds.map((id) => recordsById.get(id)).filter((node): node is NodeRecord => Boolean(node));
  }, [selectedRecord, snapshot]);
  const selectedIsDraft = Boolean(
    selectedRecord && selectedRecord.local_message_count === 0 && selectedRecord.kind === 'conversation',
  );
  const selectedIsFrozen = Boolean(selectedRecord?.frozen);

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
  const providerOptions = snapshot.config?.available_providers || [];
  const currentProvider = providerOptions.find(
    (provider) => provider.id === snapshot.config?.provider,
  );
  const fakeActive = snapshot.config?.provider === 'fake';

  return (
    <AppFrame
      platform={snapshot.platform}
      workspaceName={snapshot.workspace_name}
      actions={
        <>
          <details className="provider-picker" ref={providerMenuRef}>
            <summary
              className={`api-status ${apiReady ? 'is-ready' : 'is-missing'} ${fakeActive ? 'is-fake' : ''}`}
              aria-label="Configure API provider"
            >
              <span className="status-dot" />
              {fakeActive
                ? 'Fake context · DEV'
                : apiReady
                  ? `${currentProvider?.label || snapshot.config?.provider} ready`
                  : 'API not configured'}
              <span className="provider-chevron" aria-hidden="true">⌄</span>
            </summary>
            <div className="provider-popover">
              <div className="provider-popover-heading">
                <div>
                  <strong>API provider</strong>
                  <span>{snapshot.config?.model}</span>
                </div>
                {providerOptions.some((provider) => provider.is_dev) && <small>DEV BUILD</small>}
              </div>
              <div className="provider-options" role="list" aria-label="Available providers">
                {providerOptions.map((provider) => {
                  const selected = provider.id === snapshot.config?.provider;
                  return (
                    <button
                      key={provider.id}
                      type="button"
                      className={selected ? 'is-selected' : ''}
                      onClick={() => void switchProvider(provider.id)}
                      disabled={busy || selected}
                    >
                      <span>
                        <strong>{provider.label}</strong>
                        <small>{provider.is_dev ? 'Echo full request in chat' : provider.model}</small>
                      </span>
                      <span className="provider-check" aria-hidden="true">{selected ? '✓' : ''}</span>
                    </button>
                  );
                })}
              </div>
              <p>
                {fakeActive
                  ? 'Fake replies contain the full request and become part of the next context.'
                  : apiReady
                    ? 'Credential detected from the provider environment variable.'
                    : `Set ${apiEnvironment}, then relaunch the app.`}
              </p>
            </div>
          </details>
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
              Drop on a Draft to add context, on a discussion to create a Merge Draft, or on empty canvas to branch.
            </div>
          )}
          <ReactFlow<CanvasNode, CanvasEdge>
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick}
            onNodeContextMenu={onNodeContextMenu}
            onEdgeContextMenu={onEdgeContextMenu}
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
            proOptions={{ hideAttribution: true }}
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
                  ref={titleInputRef}
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
                      : selectedIsFrozen
                        ? `Frozen · ${selectedRecord.child_count || 0}/${selectedRecord.max_children || MAX_NODE_CHILDREN} children`
                        : `${selectedRecord.message_count} messages · Active`}
                  </span>
                </div>
              </div>

              <section className="parent-panel" aria-label={selectedIsDraft ? 'Draft parents' : 'Context parents'}>
                  <div className="parent-panel-heading">
                    <span>Context sources</span>
                    <span>{selectedIsDraft ? `${selectedParents.length}/${MAX_DRAFT_PARENTS}` : 'Captured'}</span>
                  </div>
                  {selectedParents.length ? (
                    <div className="parent-chips">
                      {selectedParents.map((parent) => (
                        <div className="parent-chip" key={parent.id} title={`${parent.id} · ${parent.title}`}>
                          <span>{parent.title}</span>
                          {selectedIsDraft ? (
                            <button
                              type="button"
                              onClick={() => void removeParent(parent.id)}
                              disabled={busy}
                              aria-label={`Remove ${parent.title} as parent`}
                            >×</button>
                          ) : (
                            <span className="parent-lock" aria-label="Captured context source">Captured</span>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p>
                      {selectedIsDraft
                        ? 'Drag from an active or frozen discussion to add context.'
                        : 'This discussion started without inherited context.'}
                    </p>
                  )}
              </section>

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

              {fakeActive && (
                <div className="fake-notice">
                  <strong>Fake context echo is active</strong>
                  <p>Each reply echoes the actual system prompt and messages sent to the provider. Replies will make later contexts grow quickly.</p>
                </div>
              )}

              {selectedIsFrozen && (
                <div className="frozen-notice">
                  <strong>Discussion frozen after branching</strong>
                  <p>Its captured context stays stable. Create a child branch to continue from this point.</p>
                </div>
              )}

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
                  disabled={!apiReady || busy || selectedIsFrozen}
                  placeholder={
                    selectedIsFrozen
                      ? 'Frozen after branching · continue in a child'
                      : apiReady
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
                <button className="send-button" disabled={!apiReady || busy || selectedIsFrozen || !message.trim()} aria-label="Send message">↑</button>
              </form>
            </>
          )}
        </aside>
      </div>

      {contextMenu && (
        <div
          className="context-menu"
          role="menu"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onPointerDown={(event) => event.stopPropagation()}
        >
          {contextMenu.kind === 'node' && contextMenuNode ? (
            <>
              <div className="context-menu-label">
                <span>{contextMenuNode.title}</span>
                <small>{contextMenuNode.id}</small>
              </div>
              <button role="menuitem" onClick={() => renameFromMenu(contextMenuNode.id)}>
                <span>Rename</span>
                <small>Edit title</small>
              </button>
              <button
                className="context-menu-danger"
                role="menuitem"
                onClick={() => void deleteNode(contextMenuNode.id)}
                disabled={!contextMenuNode.deletable || busy}
                title={contextMenuNode.deletable ? 'Delete this empty node' : 'Conversation history cannot be deleted'}
              >
                <span>Delete</span>
                <small>{contextMenuNode.deletable ? 'Empty Draft' : 'History locked'}</small>
              </button>
            </>
          ) : contextMenu.kind === 'edge' ? (
            <>
              <div className="context-menu-label">
                <span>{contextMenu.record.type === 'branch' || contextMenu.record.type === 'merge' ? 'Parent edge' : `${contextMenu.record.type} edge`}</span>
                <small>{contextMenu.record.source} → {contextMenu.record.target}</small>
              </div>
              <button
                className="context-menu-danger"
                role="menuitem"
                onClick={() => void deleteEdge(contextMenu.record)}
                disabled={!contextMenu.record.deletable || busy}
                title={contextMenu.record.deletable ? 'Delete this edge' : 'Captured context cannot be changed'}
              >
                <span>{contextMenu.record.deletable ? 'Delete edge' : 'Context captured'}</span>
                <small>{contextMenu.record.deletable ? 'Remove connection' : 'Cannot change'}</small>
              </button>
            </>
          ) : null}
        </div>
      )}

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
