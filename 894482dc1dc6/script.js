const STORAGE_KEY = 'pooh-farm-save-v1';

const CROPS = [
  { id: 'carrot', name: '胡萝卜', icon: '🥕', cost: 12, reward: 24, growTime: 12, exp: 15, unlockLevel: 1 },
  { id: 'corn', name: '玉米', icon: '🌽', cost: 20, reward: 42, growTime: 20, exp: 24, unlockLevel: 2 },
  { id: 'tomato', name: '番茄', icon: '🍅', cost: 30, reward: 65, growTime: 30, exp: 36, unlockLevel: 3 },
  { id: 'pumpkin', name: '南瓜', icon: '🎃', cost: 48, reward: 108, growTime: 48, exp: 56, unlockLevel: 4 }
];

const DEFAULT_STATE = {
  gold: 120,
  level: 1,
  exp: 0,
  plots: Array.from({ length: 3 }, (_, index) => ({ id: index + 1, cropId: null, plantedAt: null })),
  selectedCropId: 'carrot',
  logs: ['欢迎来到田园小农场，先选种子再点土地开始种植。']
};

const elements = {
  goldStat: document.querySelector('#goldStat'),
  levelStat: document.querySelector('#levelStat'),
  expStat: document.querySelector('#expStat'),
  plotStat: document.querySelector('#plotStat'),
  expBar: document.querySelector('#expBar'),
  seedList: document.querySelector('#seedList'),
  farmGrid: document.querySelector('#farmGrid'),
  logList: document.querySelector('#logList'),
  buyPlotBtn: document.querySelector('#buyPlotBtn'),
  speedUpBtn: document.querySelector('#speedUpBtn'),
  collectAllBtn: document.querySelector('#collectAllBtn'),
  resetBtn: document.querySelector('#resetBtn'),
  seedCardTemplate: document.querySelector('#seedCardTemplate')
};

let state = loadState();

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return structuredClone(DEFAULT_STATE);
    const parsed = JSON.parse(raw);
    return {
      ...structuredClone(DEFAULT_STATE),
      ...parsed,
      plots: Array.isArray(parsed.plots) && parsed.plots.length ? parsed.plots : structuredClone(DEFAULT_STATE.plots),
      logs: Array.isArray(parsed.logs) ? parsed.logs.slice(0, 8) : structuredClone(DEFAULT_STATE.logs)
    };
  } catch {
    return structuredClone(DEFAULT_STATE);
  }
}

function saveState() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function getCrop(cropId) {
  return CROPS.find((crop) => crop.id === cropId) ?? null;
}

function getExpTarget(level = state.level) {
  return 100 + (level - 1) * 50;
}

function addLog(message) {
  const time = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  state.logs.unshift(`${time} · ${message}`);
  state.logs = state.logs.slice(0, 8);
}

function gainExp(value) {
  state.exp += value;
  while (state.exp >= getExpTarget()) {
    state.exp -= getExpTarget();
    state.level += 1;
    state.gold += 30;
    addLog(`升级到 ${state.level} 级，奖励 30 金币。`);
  }
}

function getPlotProgress(plot) {
  if (!plot.cropId || !plot.plantedAt) {
    return { ready: false, ratio: 0, remaining: 0 };
  }
  const crop = getCrop(plot.cropId);
  if (!crop) {
    return { ready: false, ratio: 0, remaining: 0 };
  }
  const elapsed = Math.floor((Date.now() - plot.plantedAt) / 1000);
  const ratio = Math.min(elapsed / crop.growTime, 1);
  const remaining = Math.max(crop.growTime - elapsed, 0);
  return {
    ready: elapsed >= crop.growTime,
    ratio,
    remaining
  };
}

function formatDuration(seconds) {
  if (seconds <= 0) return '已成熟';
  if (seconds < 60) return `${seconds} 秒后成熟`;
  const minutes = Math.ceil(seconds / 60);
  return `${minutes} 分钟后成熟`;
}

function renderStats() {
  elements.goldStat.textContent = String(state.gold);
  elements.levelStat.textContent = String(state.level);
  elements.expStat.textContent = `${state.exp} / ${getExpTarget()}`;
  elements.plotStat.textContent = `${state.plots.length} 块`;
  elements.expBar.style.width = `${(state.exp / getExpTarget()) * 100}%`;
}

function renderSeeds() {
  elements.seedList.innerHTML = '';

  CROPS.forEach((crop) => {
    const template = elements.seedCardTemplate.content.cloneNode(true);
    const button = template.querySelector('.seed-card');
    const unlocked = state.level >= crop.unlockLevel;

    template.querySelector('.seed-icon').textContent = crop.icon;
    template.querySelector('.seed-name').textContent = crop.name;
    template.querySelector('.seed-cost').textContent = `${crop.cost} 金币`;
    template.querySelector('.seed-gain').textContent = `收益 ${crop.reward}`;
    template.querySelector('.seed-time').textContent = unlocked
      ? `${crop.growTime} 秒成熟 · 经验 ${crop.exp}`
      : `${crop.unlockLevel} 级解锁`;

    if (state.selectedCropId === crop.id) {
      button.classList.add('is-selected');
    }

    if (!unlocked) {
      button.classList.add('is-locked');
    }

    button.addEventListener('click', () => {
      if (!unlocked) {
        addLog(`${crop.name} 需要达到 ${crop.unlockLevel} 级才能解锁。`);
        update();
        return;
      }
      state.selectedCropId = crop.id;
      saveState();
      renderSeeds();
    });

    elements.seedList.appendChild(template);
  });
}

function renderFarm() {
  elements.farmGrid.innerHTML = '';

  state.plots.forEach((plot) => {
    const crop = getCrop(plot.cropId);
    const progress = getPlotProgress(plot);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `plot ${crop ? '' : 'empty'} ${progress.ready ? 'ready' : ''}`.trim();

    if (!crop) {
      button.innerHTML = `
        <div class="plot__name">空地 #${plot.id}</div>
        <div class="plot__crop">🌱</div>
        <div class="plot__status">点击种下 ${getCrop(state.selectedCropId)?.name ?? '作物'}</div>
      `;
    } else {
      button.innerHTML = `
        <div class="plot__name">${crop.name}</div>
        <div class="plot__crop">${crop.icon}</div>
        <div class="plot__status">${progress.ready ? '可以收获了' : formatDuration(progress.remaining)}</div>
        <div class="plot__timer">
          <div class="progress-bar"><div class="progress-fill" style="width:${progress.ratio * 100}%"></div></div>
        </div>
      `;
    }

    button.addEventListener('click', () => handlePlotClick(plot.id));
    elements.farmGrid.appendChild(button);
  });
}

function renderLogs() {
  elements.logList.innerHTML = '';
  if (!state.logs.length) {
    const item = document.createElement('li');
    item.className = 'empty-log';
    item.textContent = '还没有操作记录';
    elements.logList.appendChild(item);
    return;
  }

  state.logs.forEach((log) => {
    const item = document.createElement('li');
    item.textContent = log;
    elements.logList.appendChild(item);
  });
}

function plantCrop(plot) {
  const crop = getCrop(state.selectedCropId);
  if (!crop) return;
  if (state.level < crop.unlockLevel) {
    addLog(`${crop.name} 还未解锁。`);
    return;
  }
  if (state.gold < crop.cost) {
    addLog(`金币不足，无法购买 ${crop.name} 种子。`);
    return;
  }
  state.gold -= crop.cost;
  plot.cropId = crop.id;
  plot.plantedAt = Date.now();
  addLog(`在土地 #${plot.id} 种下了 ${crop.name}。`);
}

function harvestCrop(plot) {
  const crop = getCrop(plot.cropId);
  if (!crop) return;
  state.gold += crop.reward;
  gainExp(crop.exp);
  addLog(`收获了土地 #${plot.id} 的 ${crop.name}，获得 ${crop.reward} 金币。`);
  plot.cropId = null;
  plot.plantedAt = null;
}

function speedUpPlot(plot) {
  const crop = getCrop(plot.cropId);
  if (!crop) return false;
  const progress = getPlotProgress(plot);
  if (progress.ready) return false;
  if (state.gold < 8) {
    addLog('金币不足，无法催熟当前作物。');
    return false;
  }
  state.gold -= 8;
  plot.plantedAt = Date.now() - crop.growTime * 1000;
  addLog(`花费 8 金币催熟了土地 #${plot.id} 的 ${crop.name}。`);
  return true;
}

function handlePlotClick(plotId) {
  const plot = state.plots.find((item) => item.id === plotId);
  if (!plot) return;

  if (!plot.cropId) {
    plantCrop(plot);
  } else {
    const progress = getPlotProgress(plot);
    if (progress.ready) {
      harvestCrop(plot);
    } else {
      speedUpPlot(plot);
    }
  }

  update();
}

function buyPlot() {
  const cost = 50 + Math.max(0, state.plots.length - 3) * 20;
  if (state.gold < cost) {
    addLog(`金币不足，扩建需要 ${cost} 金币。`);
    update();
    return;
  }
  state.gold -= cost;
  const nextId = state.plots.length ? Math.max(...state.plots.map((plot) => plot.id)) + 1 : 1;
  state.plots.push({ id: nextId, cropId: null, plantedAt: null });
  addLog(`扩建了新土地 #${nextId}，花费 ${cost} 金币。`);
  update();
}

function speedUpAll() {
  if (state.gold < 20) {
    addLog('金币不足，无法进行全田催熟。');
    update();
    return;
  }
  let changed = 0;
  state.plots.forEach((plot) => {
    const crop = getCrop(plot.cropId);
    const progress = getPlotProgress(plot);
    if (crop && !progress.ready) {
      plot.plantedAt = Date.now() - crop.growTime * 1000;
      changed += 1;
    }
  });
  if (!changed) {
    addLog('当前没有可催熟的作物。');
    update();
    return;
  }
  state.gold -= 20;
  addLog(`全田催熟完成，共加速 ${changed} 块土地。`);
  update();
}

function collectAll() {
  let harvested = 0;
  state.plots.forEach((plot) => {
    if (plot.cropId && getPlotProgress(plot).ready) {
      harvestCrop(plot);
      harvested += 1;
    }
  });
  if (!harvested) {
    addLog('当前没有成熟作物可收获。');
  } else {
    addLog(`一键收获完成，共收获 ${harvested} 块土地。`);
  }
  update();
}

function resetGame() {
  const confirmed = window.confirm('确定要清空当前农场进度吗？');
  if (!confirmed) return;
  state = structuredClone(DEFAULT_STATE);
  saveState();
  update();
}

function update() {
  saveState();
  renderStats();
  renderSeeds();
  renderFarm();
  renderLogs();
}

elements.buyPlotBtn.addEventListener('click', buyPlot);
elements.speedUpBtn.addEventListener('click', speedUpAll);
elements.collectAllBtn.addEventListener('click', collectAll);
elements.resetBtn.addEventListener('click', resetGame);

update();
setInterval(renderFarm, 1000);
