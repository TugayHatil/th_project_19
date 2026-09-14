import assert from "node:assert/strict";
import { test } from "node:test";
import { dependencyGeometry, visualDependency } from "../static/src/gantt_dependency_geometry.js";

for (const type of ["FS", "SS", "FF", "SF"]) {
    for (const rtl of [false, true]) {
        test(`${type} endpoints, orthogonal routing and rounded corners (${rtl ? "RTL" : "LTR"})`, () => {
            for (const x of [-200, 0, 16, 32, 200]) {
                for (const y of [-100, 0, 20, 100]) {
                    const { path, points } = dependencyGeometry({ left: 0, top: 0 }, { left: x, top: y }, type, rtl);
                    assert.ok(!/NaN|Infinity/.test(path));
                    assert.deepEqual(points[0], { x: 0, y: 0 });
                    assert.deepEqual(points.at(-1), { x, y });
                    assert.equal(Math.sign(points[1].x), (type[0] === "F" ? 1 : -1) * (rtl ? -1 : 1));
                    assert.equal(Math.sign(points.at(-1).x - points.at(-2).x), (type[1] === "S" ? 1 : -1) * (rtl ? -1 : 1));
                    for (let i = 1; i < points.length; i++) {
                        assert.ok(points[i].x === points[i - 1].x || points[i].y === points[i - 1].y);
                    }
                }
            }
        });
    }
}

test("default FS, critical highlight and visual lag validation", () => {
    const source = { start: new Date("2026-01-01"), stop: new Date("2026-01-03"), is_critical: true };
    const target = { start: new Date("2026-01-03"), stop: new Date("2026-01-05"), is_critical: true };
    const check = (metadata) => visualDependency(source, target, metadata, "start", "stop");
    assert.deepEqual(check(), { type: "FS", lag: 0, critical: true, invalid: false });
    assert.equal(check({ type: "FS", lag: 2 }).invalid, true);
    assert.equal(check({ type: "FS", lag: -2 }).invalid, false);
    assert.equal(check({ type: "SS", lag: 2 }).invalid, false);
    assert.equal(check({ type: "FF", lag: 3 }).invalid, true);
    assert.equal(check({ type: "SF", lag: 4 }).invalid, false);
    assert.equal(source.stop.toISOString(), "2026-01-03T00:00:00.000Z");
});

test("route 2000 links with finite geometry", () => {
    const start = performance.now();
    for (let i = 0; i < 2000; i++) {
        const result = dependencyGeometry({ left: i % 1000, top: i % 50 * 40 }, { left: i % 600, top: (i + 3) % 50 * 40 }, ["FS", "SS", "FF", "SF"][i % 4]);
        assert.ok(!/NaN|Infinity/.test(result.path));
    }
    console.log(`2000-link geometry calculation: ${(performance.now() - start).toFixed(1)} ms (not an Odoo scrolling benchmark)`);
});
