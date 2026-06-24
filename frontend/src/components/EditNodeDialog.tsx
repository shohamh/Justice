import { FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  DndContext,
  DragEndEvent,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { updateNode } from "../api/hierarchy";
import {
  LevelTypeDTO,
  createLevelType,
  deleteLevelType,
  reorderLevelTypes,
} from "../api/levelTypes";
import { useLevelTypes } from "../hooks/useLevelTypes";

interface Props {
  nodeId: string;
  currentName: string;
  currentLevel: string;
  parentRank: number | null;
  minChildRank: number | null;
  isAdmin: boolean;
  nodesUsingLevel: (key: string) => boolean;
  onClose: () => void;
  onRenamed: () => void;
}

function SortableLevelTypeRow({
  type,
  canDelete,
  onDelete,
}: {
  type: LevelTypeDTO;
  canDelete: boolean;
  onDelete: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: type.id });
  const style = { transform: CSS.Transform.toString(transform), transition };

  return (
    <li
      ref={setNodeRef}
      style={style}
      className="flex items-center gap-2 py-1 px-1 text-sm"
      data-testid={`level-type-row-${type.key}`}
    >
      <span {...attributes} {...listeners} className="cursor-grab text-gray-400 select-none">⠿</span>
      <span className="text-xs text-gray-400 w-6 text-center">{type.rank}</span>
      <span className="flex-1">{type.label}</span>
      {canDelete && (
        <button
          type="button"
          className="text-red-500 hover:underline text-xs"
          onClick={onDelete}
          data-testid={`level-type-delete-${type.key}`}
        >
          ✕
        </button>
      )}
    </li>
  );
}

export default function EditNodeDialog({
  nodeId,
  currentName,
  currentLevel,
  parentRank,
  minChildRank,
  isAdmin,
  nodesUsingLevel,
  onClose,
  onRenamed,
}: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState(currentName);
  const [level, setLevel] = useState(currentLevel);
  const { levelTypes, refresh } = useLevelTypes();
  const [orderedTypes, setOrderedTypes] = useState<LevelTypeDTO[] | null>(null);
  const [reorderDirty, setReorderDirty] = useState(false);
  const [violations, setViolations] = useState<{ parent: string; child: string }[] | null>(null);
  const [newTypeLabel, setNewTypeLabel] = useState("");
  const [managerOpen, setManagerOpen] = useState(false);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));

  const validLevelOptions = levelTypes.filter((lt) => {
    if (parentRank !== null && lt.rank <= parentRank) return false;
    if (minChildRank !== null && lt.rank >= minChildRank) return false;
    return true;
  });

  const displayTypes = orderedTypes ?? levelTypes;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    await updateNode(nodeId, { name, level: level !== currentLevel ? level : undefined });
    onRenamed();
    onClose();
  }

  function onDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const base = orderedTypes ?? levelTypes;
    const oldIndex = base.findIndex((t) => t.id === active.id);
    const newIndex = base.findIndex((t) => t.id === over.id);
    setOrderedTypes(arrayMove(base, oldIndex, newIndex));
    setReorderDirty(true);
    setViolations(null);
  }

  async function onSaveOrder() {
    if (!orderedTypes) return;
    try {
      await reorderLevelTypes(orderedTypes.map((t) => t.id));
      setReorderDirty(false);
      setOrderedTypes(null);
      setViolations(null);
      await refresh();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: { violations?: { parent: string; child: string }[] } } } })
        ?.response?.data?.detail;
      if (detail?.violations) {
        setViolations(detail.violations);
      } else {
        alert(t("errors.generic"));
      }
    }
  }

  async function onAddType(e: FormEvent) {
    e.preventDefault();
    if (!newTypeLabel.trim()) return;
    const key = newTypeLabel.trim().toLowerCase().replace(/\s+/g, "_");
    await createLevelType(key, newTypeLabel.trim());
    setNewTypeLabel("");
    await refresh();
  }

  async function onDeleteType(type: LevelTypeDTO) {
    if (nodesUsingLevel(type.key)) return;
    await deleteLevelType(type.id);
    await refresh();
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-96 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()} data-testid="edit-node-dialog">
        <h3 className="font-semibold mb-4 dark:text-gray-100">{t("team.edit_node")}</h3>
        <form onSubmit={onSubmit} className="space-y-3">
          <input className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={name} onChange={(e) => setName(e.target.value)} required data-testid="edit-node-name-input" />
          <select className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={level} onChange={(e) => setLevel(e.target.value)} data-testid="edit-node-level-select">
            {validLevelOptions.map((lt) => (
              <option key={lt.id} value={lt.key}>{lt.label}</option>
            ))}
          </select>
          <div className="flex justify-end gap-2">
            <button type="button" className="border rounded px-3 py-1 dark:border-gray-600 dark:text-gray-300" onClick={onClose}>{t("team.cancel")}</button>
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="edit-node-submit">{t("duty_config.save")}</button>
          </div>
        </form>

        {isAdmin && (
          <div className="mt-4 border-t pt-3 dark:border-gray-600">
            <button
              type="button"
              className="text-sm text-indigo-600 dark:text-indigo-300"
              onClick={() => setManagerOpen((v) => !v)}
              data-testid="level-type-manager-toggle"
            >
              {t("team.level_type_manager")}
            </button>

            {managerOpen && (
              <div className="mt-2 space-y-2" data-testid="level-type-manager">
                <DndContext sensors={sensors} onDragEnd={onDragEnd}>
                  <SortableContext items={displayTypes.map((t) => t.id)} strategy={verticalListSortingStrategy}>
                    <ul>
                      {displayTypes.map((type) => (
                        <SortableLevelTypeRow
                          key={type.id}
                          type={type}
                          canDelete={!nodesUsingLevel(type.key)}
                          onDelete={() => void onDeleteType(type)}
                        />
                      ))}
                    </ul>
                  </SortableContext>
                </DndContext>

                {violations && (
                  <div className="text-xs text-red-500" data-testid="level-type-violations">
                    <p>{t("team.level_type_reorder_violations")}</p>
                    <ul>
                      {violations.map((v, i) => (
                        <li key={i}>{v.parent} → {v.child}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {reorderDirty && (
                  <button
                    type="button"
                    className="bg-indigo-600 text-white px-2 py-1 rounded text-xs"
                    onClick={() => void onSaveOrder()}
                    data-testid="level-type-save-order"
                  >
                    {t("team.level_type_save_order")}
                  </button>
                )}

                <form onSubmit={(e) => void onAddType(e)} className="flex gap-1">
                  <input
                    className="border rounded p-1 flex-1 text-xs dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                    value={newTypeLabel}
                    onChange={(e) => setNewTypeLabel(e.target.value)}
                    placeholder={t("team.level_type_new_label")}
                    data-testid="level-type-new-input"
                  />
                  <button type="submit" className="bg-indigo-600 text-white px-2 py-1 rounded text-xs" data-testid="level-type-add-submit">
                    {t("team.level_type_add")}
                  </button>
                </form>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
