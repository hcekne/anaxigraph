import {
  architectureFor,
  architecturePalettes,
  byId,
  currentTheme,
  escapeAttr,
  escapeHtml,
  format,
  hash,
  humanize,
  mix,
  readThemeColors,
  state,
} from "/assets/dashboard-core.js";

export function buildGroupIndex(groups) {
  state.groupParents.clear();
  state.groupRoots = groups;
  const visit = (group, root) => {
    state.groupParents.set(group.name, root);
    (group.children || []).forEach((child) => visit(child, root));
  };
  groups.forEach((group) => visit(group, group.name));
}

export function effectiveGroup(node) {
  const placement = architectureFor(node);
  if (placement) return placement.subsystem || placement.area || "ungrouped";
  if (state.mapLayer === "policy") return "unconfigured";
  return node.declared_group || node.inferred_group || "ungrouped";
}

export function rootGroup(node) {
  const placement = architectureFor(node);
  const group = effectiveGroup(node);
  return placement?.area || state.groupParents.get(group) || group;
}

export function visibleGraphNodes() {
  return (state.graph.nodes || []).filter((node) => !state.hiddenGroups.has(rootGroup(node)));
}

export function renderGraphAreaOptions() {
  const counts = new Map();
  (state.graph.nodes || []).forEach((node) => {
    const root = rootGroup(node);
    counts.set(root, (counts.get(root) || 0) + 1);
  });
  const order = new Map(state.groupRoots.map((group, index) => [group.name, index]));
  const roots = [...counts].sort(([left], [right]) => (
    (order.get(left) ?? 10_000) - (order.get(right) ?? 10_000)
      || left.localeCompare(right)
  ));
  byId("graph-area-options").innerHTML = roots.map(([root, count]) => (
    `<label><input type="checkbox" data-graph-area="${escapeAttr(root)}" ${state.hiddenGroups.has(root) ? "" : "checked"} /><i style="background:${groupColor(root)}"></i><span>${escapeHtml(humanize(root))}</span><em>${format.format(count)}</em></label>`
  )).join("");
  const visible = roots.filter(([root]) => !state.hiddenGroups.has(root)).length;
  byId("graph-area-count").textContent = visible === roots.length
    ? `all ${roots.length}`
    : `${visible}/${roots.length}`;
}

export function architectureColor(group) {
  const parent = state.groupParents.get(group) || group;
  const base = groupColor(parent);
  if (parent === group) return base;
  return mix(base, architectureMixTarget(), 0.08 + (hash(group) % 13) / 100);
}

export function architectureMixTarget() {
  return currentTheme() === "high-contrast" ? "#000000" : "#ffffff";
}

function weightedRectangles(items, bounds, gap = 8) {
  const rectangles = new Map();
  const partition = (entries, rectangle) => {
    if (!entries.length) return;
    if (entries.length === 1) {
      const inset = Math.min(gap, rectangle.width * 0.08, rectangle.height * 0.08);
      rectangles.set(entries[0].key, {
        x: rectangle.x + inset,
        y: rectangle.y + inset,
        width: Math.max(10, rectangle.width - inset * 2),
        height: Math.max(10, rectangle.height - inset * 2),
      });
      return;
    }
    const total = entries.reduce((sum, item) => sum + item.weight, 0);
    let split = 1;
    let firstWeight = entries[0].weight;
    while (split < entries.length - 1 && firstWeight + entries[split].weight <= total / 2) {
      firstWeight += entries[split].weight;
      split += 1;
    }
    const ratio = Math.max(0.08, Math.min(0.92, firstWeight / total));
    if (rectangle.width >= rectangle.height) {
      const firstWidth = rectangle.width * ratio;
      partition(entries.slice(0, split), { ...rectangle, width: firstWidth });
      partition(entries.slice(split), {
        x: rectangle.x + firstWidth,
        y: rectangle.y,
        width: rectangle.width - firstWidth,
        height: rectangle.height,
      });
    } else {
      const firstHeight = rectangle.height * ratio;
      partition(entries.slice(0, split), { ...rectangle, height: firstHeight });
      partition(entries.slice(split), {
        x: rectangle.x,
        y: rectangle.y + firstHeight,
        width: rectangle.width,
        height: rectangle.height - firstHeight,
      });
    }
  };
  partition(items, bounds);
  return rectangles;
}

function squarifiedRectangles(items, bounds, gap = 8) {
  const rectangles = new Map();
  if (!items.length || bounds.width <= 0 || bounds.height <= 0) return rectangles;
  const totalWeight = items.reduce((sum, item) => sum + item.weight, 0) || 1;
  const areaScale = bounds.width * bounds.height / totalWeight;
  const remainingItems = [...items]
    .sort((left, right) => right.weight - left.weight || left.key.localeCompare(right.key))
    .map((item) => ({ ...item, area: item.weight * areaScale }));
  let remaining = { ...bounds };
  let row = [];
  const worstAspect = (entries, side) => {
    if (!entries.length || side <= 0) return Number.POSITIVE_INFINITY;
    const total = entries.reduce((sum, item) => sum + item.area, 0);
    const largest = Math.max(...entries.map((item) => item.area));
    const smallest = Math.min(...entries.map((item) => item.area));
    return Math.max(
      side * side * largest / (total * total),
      total * total / (side * side * smallest),
    );
  };
  const placeRow = (entries) => {
    const total = entries.reduce((sum, item) => sum + item.area, 0);
    const inset = gap / 2;
    if (remaining.width >= remaining.height) {
      const rowWidth = total / Math.max(remaining.height, 1);
      let cursor = remaining.y;
      entries.forEach((item) => {
        const itemHeight = item.area / Math.max(rowWidth, 1);
        rectangles.set(item.key, {
          x: remaining.x + inset,
          y: cursor + inset,
          width: Math.max(10, rowWidth - gap),
          height: Math.max(10, itemHeight - gap),
        });
        cursor += itemHeight;
      });
      remaining = {
        x: remaining.x + rowWidth,
        y: remaining.y,
        width: Math.max(0, remaining.width - rowWidth),
        height: remaining.height,
      };
    } else {
      const rowHeight = total / Math.max(remaining.width, 1);
      let cursor = remaining.x;
      entries.forEach((item) => {
        const itemWidth = item.area / Math.max(rowHeight, 1);
        rectangles.set(item.key, {
          x: cursor + inset,
          y: remaining.y + inset,
          width: Math.max(10, itemWidth - gap),
          height: Math.max(10, rowHeight - gap),
        });
        cursor += itemWidth;
      });
      remaining = {
        x: remaining.x,
        y: remaining.y + rowHeight,
        width: remaining.width,
        height: Math.max(0, remaining.height - rowHeight),
      };
    }
  };
  while (remainingItems.length) {
    const candidate = remainingItems[0];
    const side = Math.min(remaining.width, remaining.height);
    if (!row.length || worstAspect([...row, candidate], side) <= worstAspect(row, side)) {
      row.push(remainingItems.shift());
    } else {
      placeRow(row);
      row = [];
    }
  }
  if (row.length) placeRow(row);
  return rectangles;
}

export function layoutGraph(resetView = true) {
  const nodes = visibleGraphNodes();
  const canvas = byId("graph-canvas");
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return;
  const grouped = new Map();
  nodes.forEach((node) => {
    const group = effectiveGroup(node);
    if (!grouped.has(group)) grouped.set(group, []);
    grouped.get(group).push(node);
  });
  const rootOrder = new Map(state.groupRoots.map((group, index) => [group.name, index]));
  const roots = new Map();
  const seedGroup = (map, group) => {
    if (!map.has(group.name)) map.set(group.name, []);
    (group.children || []).forEach((child) => seedGroup(map, child));
  };
  state.groupRoots.filter((root) => !state.hiddenGroups.has(root.name)).forEach((root) => {
    const map = new Map();
    seedGroup(map, root);
    roots.set(root.name, map);
  });
  grouped.forEach((members, group) => {
    const root = state.groupParents.get(group) || rootGroup(members[0]);
    if (!roots.has(root)) roots.set(root, new Map());
    roots.get(root).set(group, members);
  });
  const rootNames = [...roots.keys()]
    .filter((root) => [...roots.get(root).values()].some((members) => members.length))
    .sort((left, right) => {
      const leftOrder = rootOrder.get(left) ?? 10_000;
      const rightOrder = rootOrder.get(right) ?? 10_000;
      return leftOrder - rightOrder || left.localeCompare(right);
    });
  const rootEntries = rootNames.map((root) => {
    const nodeCount = [...roots.get(root).values()].reduce((sum, members) => sum + members.length, 0);
    return { key: root, weight: Math.max(48, 28 + humanize(root).length * 2.4, nodeCount) };
  });
  const rootRectangles = squarifiedRectangles(
    rootEntries, { x: 0, y: 0, width, height }, 10,
  );
  state.positions.clear();
  state.groupRegions = [];
  rootNames.forEach((root) => {
    const rectangle = rootRectangles.get(root);
    if (!rectangle) return;
    const nodeCount = [...roots.get(root).values()].reduce((sum, members) => sum + members.length, 0);
    const region = { root, ...rectangle, nodeCount, color: groupColor(root) };
    region.labelLines = regionLabelLines(region);
    region.labelOverflow = region.labelLines.some((line) => (
      estimateLabelWidth(line) > Math.max(1, region.width - 20)
    )) || region.height < region.labelLines.length * 14 + 18;
    state.groupRegions.push(region);
    const headerHeight = Math.min(
      Math.max(28, region.labelLines.length * 14 + 8), Math.max(28, region.height * 0.34),
    );
    const subgroupEntries = [...roots.get(root).entries()]
      .filter(([, members]) => members.length)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([group, members]) => ({ key: group, weight: members.length }));
    const subgroupRectangles = weightedRectangles(subgroupEntries, {
      x: region.x + 5,
      y: region.y + headerHeight,
      width: Math.max(10, region.width - 10),
      height: Math.max(10, region.height - headerHeight - 5),
    }, 3);
    subgroupEntries.forEach(({ key: group }) => {
      const subregion = subgroupRectangles.get(group);
      const members = [...roots.get(root).get(group)].sort((left, right) => (
        left.path.localeCompare(right.path)
      ));
      if (!subregion || !members.length) return;
      const innerWidth = Math.max(8, subregion.width - 8);
      const innerHeight = Math.max(8, subregion.height - 8);
      const columns = Math.max(1, Math.ceil(Math.sqrt(members.length * innerWidth / innerHeight)));
      const rows = Math.ceil(members.length / columns);
      const cellWidth = innerWidth / columns;
      const cellHeight = innerHeight / Math.max(rows, 1);
      members.forEach((node, index) => {
        const value = hash(node.path);
        const column = index % columns;
        const row = Math.floor(index / columns);
        const jitter = Math.min(cellWidth, cellHeight) * 0.12;
        state.positions.set(String(node.id), {
          x: subregion.x + 4 + (column + 0.5) * cellWidth + ((((value & 255) / 255) - 0.5) * jitter),
          y: subregion.y + 4 + (row + 0.5) * cellHeight + (((((value >>> 8) & 255) / 255) - 0.5) * jitter),
          group,
        });
      });
    });
  });
  canvas.dataset.regionCount = String(state.groupRegions.length);
  canvas.dataset.visibleNodeCount = String(nodes.length);
  canvas.dataset.labelOverflow = String(
    state.groupRegions.filter((region) => region.labelOverflow).length,
  );
  if (resetView) state.transform = { x: 0, y: 0, scale: 1 };
}

function estimateLabelWidth(value) {
  return String(value).length * 6.35;
}

function regionLabelLines(region) {
  const name = humanize(region.root);
  const count = `${format.format(region.nodeCount)} module${region.nodeCount === 1 ? "" : "s"}`;
  const available = Math.max(40, region.width - 20);
  if (estimateLabelWidth(`${name} · ${format.format(region.nodeCount)}`) <= available) {
    return [`${name} · ${format.format(region.nodeCount)}`];
  }
  const lines = [];
  let current = "";
  name.split(" ").forEach((word) => {
    const candidate = current ? `${current} ${word}` : word;
    if (current && estimateLabelWidth(candidate) > available) {
      lines.push(current);
      current = word;
    } else current = candidate;
  });
  if (current) lines.push(current);
  lines.push(count);
  return lines;
}

export function nodeMetric(node) {
  return Math.max(0, Number(node[byId("size-select").value] || 0));
}

export function nodeRadius(node, maximum) {
  return 3.2 + Math.sqrt(nodeMetric(node) / Math.max(maximum, 1)) * 10;
}

export function groupColor(group) {
  const colors = architecturePalettes[currentTheme()] || architecturePalettes["constellation-light"];
  return colors[Math.abs(hash(group)) % colors.length];
}

function heat(value, maximum, cool = null, hot = null) {
  const theme = state.themeColors || readThemeColors();
  const amount = Math.min(1, Math.max(0, value / Math.max(maximum, 1)));
  return mix(cool || theme.cool, hot || theme.hot, amount);
}

export function nodeColor(node) {
  const overlay = byId("overlay-select").value;
  const theme = state.themeColors || readThemeColors();
  if (overlay === "architecture") return architectureColor(effectiveGroup(node));
  if (overlay === "coupling") return heat(Number(node.fan_in) + Number(node.fan_out), 25, theme.low, theme.hot);
  if (overlay === "complexity") return heat(Number(node.complexity), 60, theme.cool, theme.hot);
  if (overlay === "coverage") return node.line_coverage == null ? theme.missing : heat(1 - Number(node.line_coverage), 1, theme.cool, theme.hot);
  if (overlay === "change") return heat(Number(node.change_count || 0), 30, theme.low, theme.warm);
  if (overlay === "drift") return node.declared_group && node.inferred_group && node.declared_group !== node.inferred_group ? theme.hot : theme.drift;
  if (overlay === "dead-code") {
    const module = state.modules.find((item) => item.path === node.path);
    const dead = module?.active_findings?.some((finding) => finding.finding_type === "possible_dead_code");
    return dead ? theme.warm : theme.idle;
  }
  if (overlay === "agent") {
    if (state.conflictPaths.has(node.path)) return theme.hot;
    if (state.protectedPaths.has(node.path)) return theme.warm;
    if (state.highlightedPaths.has(node.path)) return theme.cool;
    return theme.safe;
  }
  return theme.cool;
}
