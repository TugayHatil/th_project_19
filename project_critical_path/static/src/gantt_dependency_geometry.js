export function dependencyGeometry(source, target, type = "FS", rtl = false) {
    const direction = rtl ? -1 : 1;
    const sourceDirection = (type[0] === "F" ? 1 : -1) * direction;
    const targetDirection = (type[1] === "F" ? 1 : -1) * direction;
    const start = { x: source.left, y: source.top };
    const end = { x: target.left, y: target.top };
    const exit = { x: start.x + sourceDirection * 16, y: start.y };
    const entry = { x: end.x + targetDirection * 16, y: end.y };
    let middle;
    if (sourceDirection === targetDirection) {
        const x = sourceDirection > 0 ? Math.max(exit.x, entry.x) : Math.min(exit.x, entry.x);
        middle = [{ x, y: start.y }, { x, y: end.y }];
    } else if ((entry.x - exit.x) * sourceDirection >= 0) {
        const x = (exit.x + entry.x) / 2;
        middle = [{ x, y: start.y }, { x, y: end.y }];
    } else {
        const y = Math.abs(end.y - start.y) >= 36 ? (start.y + end.y) / 2 : Math.min(start.y, end.y) - 24;
        middle = [exit, { x: exit.x, y }, { x: entry.x, y }, entry];
    }
    const points = [start, ...middle, end].filter((point, index, all) =>
        !index || point.x !== all[index - 1].x || point.y !== all[index - 1].y
    );
    let path = `M ${start.x} ${start.y}`;
    for (let i = 1; i < points.length - 1; i++) {
        const before = points[i - 1];
        const corner = points[i];
        const after = points[i + 1];
        const incoming = Math.hypot(corner.x - before.x, corner.y - before.y);
        const outgoing = Math.hypot(after.x - corner.x, after.y - corner.y);
        const radius = Math.min(4, incoming / 2, outgoing / 2);
        const a = { x: corner.x + (before.x - corner.x) * radius / incoming, y: corner.y + (before.y - corner.y) * radius / incoming };
        const b = { x: corner.x + (after.x - corner.x) * radius / outgoing, y: corner.y + (after.y - corner.y) * radius / outgoing };
        path += ` L ${a.x} ${a.y} Q ${corner.x} ${corner.y} ${b.x} ${b.y}`;
    }
    path += ` L ${end.x} ${end.y}`;
    const center = middle[Math.floor(middle.length / 2)];
    return { path, points, label: { x: center.x + 6, y: center.y - 6 } };
}

export function visualDependency(source, target, metadata, startField, stopField) {
    const type = metadata?.type || "FS";
    const lag = metadata?.lag || 0;
    const sourceDate = source[type[0] === "F" ? stopField : startField];
    const targetDate = target[type[1] === "F" ? stopField : startField];
    return {
        type,
        lag,
        critical: Boolean(source.is_critical && target.is_critical),
        invalid: Boolean(sourceDate && targetDate && Number(targetDate) < Number(sourceDate) + lag * 86400000),
    };
}
