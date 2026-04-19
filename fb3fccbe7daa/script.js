const CROPS = {
  wheat: { name: '小麦', seedCost: 8, growTime: 20, sellPrice: 16, exp: 8, icon: '🌾' },
  carrot: { name: '胡萝卜', seedCost: 15, growTime: 35, sellPrice: 32, exp: 14, icon: '🥕' },
  corn: { name: '玉米', seedCost: 28, growTime: 55, sellPrice: 58, exp: 24, icon: '🌽' },
  strawberry: { name: '草莓', seedCost: 45, growTime: 90, sellPrice: 94, exp: 38, icon: '🍓' }
};

const UPGRADES = [
  {
    key: 'watering',
    name: '喷壶升级',
    desc: '所有作物生长时间减少 15%。',
    cost: 180,
    apply(state) { state.bonuses.growMultiplier *= 0.85; }
  },
  {
    key: 'basket',
    name: '仓库扩容',
    desc: '仓库上限 +20。',
    cost: 220,
    apply(state) { state.maxStorage += 20; }
  },
  {
    key: 'boots',
    name: '农夫靴',
    desc: '体力上限 +8。',
    cost: 260,
    apply(state) { state.maxEnergy += 8; state.energy += 8; }
  }
];

const WEATHER_TYPES = [
  { key: 'sunny', name: '晴天', grow: 1, bonusText: '正常生长' },
  { key: 'rainy', name: '雨天', grow: 0.85, bonusText: '作物生长加快 15%' },
  { key: 'windy', name: '大风', grow: 1.1, bonusText: '作物生长减慢 10%' }
];

const STORAGE_KEY = 'farm-grow-game-save-v1';

const els = {
  gold: document.getElementById('gold'),
  level: document.getElementById('level'),
  exp: document.getElementById('exp'),
  energy: document.getElementById('energy'),
  storage: document.getElementById('storage'),
  weather: document.getElementById('weather'),
  expBar: document.getElementById('expBar'),
  tips: document.getElementById('tips'),
  farmGrid: document.getElementById('farmGrid'),
  seeds: document.getElementById('tab-seeds'),
  upgrades: document.getElementById('tab-upgrades'),
  bag: document.getElementById('tab-bag'),
  saveBtn: document.getElementById('saveBtn'),
  unlockPlotBtn: document.getElementById('unlockPlotBtn'),
  restBtn: document.getElementById('restBtn'),
  plotTemplate: document.getElementById('plotTemplate')
};

function getDefaultState() {
  return {
    gold: 120,
    level: 1,
    exp: 0,
    expToNext: 100,
    energy: 18,
    maxEnergy: 18,
    maxStorage: 40,
    inventory: {},
    unlockedPlots: 6,
    bonuses: {
      growMultiplier: 1
    },
    boughtUpgrades: [],
    weather: pickDailyWeather(),
    lastWeatherDate: new Date().toDateString(),
    plots: Array.from({ length: 12 }, (_, i) => ({
      id: i,
      cropKey: null,
      plantedAt: null,
      growDuration: null,
      status: i < 6 ? 'empty' : 'locked'
    }))
  };
}

function pickDailyWeather() {
  const day = Math.floor(Date.now() / (1000 * 60 * 60 * 24));
  return WEATHER_TYPES[day % WEATHER_TYPES.length];
}

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return getDefaultState();
    const saved = JSON.parse(raw);
    const state = { ...getDefaultState(), ...saved };
    if (!Array.isArray(state.plots) || state.plots.length !== 12) return getDefaultState();
    if (state.lastWeatherDate !== new Date().toDateString()) {
      state.weather = pickDailyWeather();
      state.lastWeatherDate = new Date().toDateString();
    }
    state.plots.forEach((plot, i) => {
      if (i >= state.unlockedPlots) plot.status = 'locked';
      else if (plot.status === 'locked') plot.status = 'empty';
    });
    return state;
  } catch {
    return getDefaultState();
  }
}

let state = loadState();

function saveState(showTip = false) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  if (showTip) setTip('已保存到浏览器本地，下次打开还能继续经营农场。');
}

function setTip(text) {
  els.tips.textContent = text;
}

function currentStorageCount() {
  return Object.values(state.inventory).reduce((sum, num) => sum + num, 0);
}

function gainExp(amount) {
  state.exp += amount;
  while (state.exp >= state.expToNext) {
    state.exp -= state.expToNext;
    state.level += 1;
    state.expToNext = Math.round(state.expToNext * 1.25);
    state.maxEnergy += 4;
    state.energy = state.maxEnergy;
    state.gold += 50;
    setTip(`升级到 ${state.level} 级，获得 50 金币，体力回满。`);
  }
}

function useEnergy(amount) {
  if (state.energy < amount) {
    setTip('体力不足，先休息一下。');
    return false;
  }
  state.energy -= amount;
  return true;
}

function getPlotDisplay(plot) {
  if (plot.status === 'locked') return { name: '未解锁', status: '点击上方按钮解锁', timer: '🔒' };
  if (plot.status === 'empty') return { name: '空地', status: '点击选择种植', timer: '可播种' };
  const crop = CROPS[plot.cropKey];
  const remain = getRemainingTime(plot);
  if (remain <= 0) return { name: `${crop.icon} ${crop.name}`, status: '已成熟，点击收获', timer: '可收获' };
  return { name: `${crop.icon} ${crop.name}`, status: '正在生长', timer: `${remain} 秒` };
}

function getRemainingTime(plot) {
  if (!plot.plantedAt || !plot.growDuration) return 0;
  const pass = Math.floor((Date.now() - plot.plantedAt) / 1000);
  return Math.max(0, plot.growDuration - pass);
}

function updatePlotStatuses() {
  state.plots.forEach((plot, i) => {
    if (i >= state.unlockedPlots) {
      plot.status = 'locked';
      return;
    }
    if (plot.cropKey && getRemainingTime(plot) <= 0) {
      plot.status = 'ready';
    } else if (plot.cropKey) {
      plot.status = 'growing';
    } else {
      plot.status = 'empty';
    }
  });
}

function renderStats() {
  els.gold.textContent = state.gold;
  els.level.textContent = state.level;
  els.exp.textContent = `${state.exp} / ${state.expToNext}`;
  els.energy.textContent = `${state.energy} / ${state.maxEnergy}`;
  els.storage.textContent = `${currentStorageCount()} / ${state.maxStorage}`;
  els.weather.textContent = `${state.weather.name} · ${state.weather.bonusText}`;
  els.expBar.style.width = `${(state.exp / state.expToNext) * 100}%`;
}

function renderFarm() {
  updatePlotStatuses();
  els.farmGrid.innerHTML = '';
  state.plots.forEach((plot, index) => {
    const node = els.plotTemplate.content.firstElementChild.cloneNode(true);
    node.classList.toggle('locked', plot.status === 'locked');
    node.classList.toggle('growing', plot.status === 'growing');
    node.classList.toggle('ready', plot.status === 'ready');
    const display = getPlotDisplay(plot);
    node.querySelector('.plot-name').textContent = `地块 ${index + 1} · ${display.name}`;
    node.querySelector('.plot-status').textContent = display.status;
    node.querySelector('.plot-timer').textContent = display.timer;
    node.addEventListener('click', () => handlePlotClick(index));
    els.farmGrid.appendChild(node);
  });
}

function renderSeeds() {
  const wrap = document.createElement('div');
  wrap.className = 'card-list';
  Object.entries(CROPS).forEach(([key, crop]) => {
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <div class="card-row">
        <h3>${crop.icon} ${crop.name}</h3>
        <span class="badge">种子 ${crop.seedCost} 金币</span>
      </div>
      <p>成熟时间 ${crop.growTime} 秒，出售价格 ${crop.sellPrice} 金币，收获经验 ${crop.exp}。</p>
      <button>设为当前种植作物</button>
    `;
    card.querySelector('button').addEventListener('click', () => {
      state.selectedCrop = key;
      setTip(`已选择 ${crop.name}，点击空地即可播种。`);
      saveState();
      render();
    });
    wrap.appendChild(card);
  });
  if (state.selectedCrop) {
    const current = document.createElement('p');
    current.innerHTML = `当前选中：<strong>${CROPS[state.selectedCrop].icon} ${CROPS[state.selectedCrop].name}</strong>`;
    wrap.prepend(current);
  }
  els.seeds.innerHTML = '';
  els.seeds.appendChild(wrap);
}

function renderUpgrades() {
  const wrap = document.createElement('div');
  wrap.className = 'card-list';
  UPGRADES.forEach((upgrade) => {
    const bought = state.boughtUpgrades.includes(upgrade.key);
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <div class="card-row">
        <h3>${upgrade.name}</h3>
        <span class="badge">${upgrade.cost} 金币</span>
      </div>
      <p>${upgrade.desc}</p>
      <button ${bought ? 'disabled' : ''}>${bought ? '已购买' : '购买升级'}</button>
    `;
    card.querySelector('button').addEventListener('click', () => buyUpgrade(upgrade.key));
    wrap.appendChild(card);
  });
  els.upgrades.innerHTML = '';
  els.upgrades.appendChild(wrap);
}

function renderBag() {
  els.bag.innerHTML = '';
  const wrap = document.createElement('div');
  const entries = Object.entries(state.inventory).filter(([, count]) => count > 0);
  if (!entries.length) {
    wrap.innerHTML = '<p>仓库还是空的，先去种点东西吧。</p>';
  } else {
    entries.forEach(([key, count]) => {
      const crop = CROPS[key];
      const row = document.createElement('div');
      row.className = 'inventory-item';
      row.innerHTML = `
        <span>${crop.icon} ${crop.name} × ${count}</span>
        <button>全部出售（${count * crop.sellPrice}）</button>
      `;
      row.querySelector('button').addEventListener('click', () => sellCrop(key));
      wrap.appendChild(row);
    });
  }
  els.bag.appendChild(wrap);
}

function buyUpgrade(key) {
  const upgrade = UPGRADES.find((item) => item.key === key);
  if (!upgrade || state.boughtUpgrades.includes(key)) return;
  if (state.gold < upgrade.cost) {
    setTip('金币不够，先卖出一些农作物。');
    return;
  }
  state.gold -= upgrade.cost;
  state.boughtUpgrades.push(key);
  upgrade.apply(state);
  setTip(`已购买 ${upgrade.name}。`);
  saveState();
  render();
}

function sellCrop(key) {
  const count = state.inventory[key] || 0;
  if (!count) return;
  const crop = CROPS[key];
  const income = count * crop.sellPrice;
  state.gold += income;
  state.inventory[key] = 0;
  setTip(`成功出售 ${crop.name} × ${count}，获得 ${income} 金币。`);
  saveState();
  render();
}

function plantCrop(plotIndex) {
  const plot = state.plots[plotIndex];
  if (!state.selectedCrop) {
    setTip('先去种子商店选择一个作物。');
    return;
  }
  const crop = CROPS[state.selectedCrop];
  if (state.gold < crop.seedCost) {
    setTip('金币不够，无法购买种子。');
    return;
  }
  if (!useEnergy(2)) return;
  state.gold -= crop.seedCost;
  plot.cropKey = state.selectedCrop;
  plot.plantedAt = Date.now();
  plot.growDuration = Math.round(crop.growTime * state.bonuses.growMultiplier * state.weather.grow);
  plot.status = 'growing';
  setTip(`已在地块 ${plotIndex + 1} 种下 ${crop.name}。`);
  saveState();
  render();
}

function harvestCrop(plotIndex) {
  const plot = state.plots[plotIndex];
  const crop = CROPS[plot.cropKey];
  if (!crop) return;
  if (currentStorageCount() >= state.maxStorage) {
    setTip('仓库已满，先去出售一些农作物。');
    return;
  }
  if (!useEnergy(1)) return;
  state.inventory[plot.cropKey] = (state.inventory[plot.cropKey] || 0) + 1;
  gainExp(crop.exp);
  plot.cropKey = null;
  plot.plantedAt = null;
  plot.growDuration = null;
  plot.status = 'empty';
  setTip(`收获了 ${crop.name}，已放入仓库。`);
  saveState();
  render();
}

function handlePlotClick(index) {
  const plot = state.plots[index];
  updatePlotStatuses();
  if (plot.status === 'locked') {
    setTip('这个地块还没解锁。');
    return;
  }
  if (plot.status === 'empty') {
    plantCrop(index);
  } else if (plot.status === 'ready') {
    harvestCrop(index);
  } else {
    const remain = getRemainingTime(plot);
    setTip(`${CROPS[plot.cropKey].name} 还需要 ${remain} 秒成熟。`);
  }
}

function unlockPlot() {
  if (state.unlockedPlots >= state.plots.length) {
    setTip('所有地块都已经解锁。');
    return;
  }
  const cost = 150 + (state.unlockedPlots - 6) * 60;
  if (state.gold < cost) {
    setTip(`金币不够，解锁下一个地块需要 ${cost}。`);
    return;
  }
  state.gold -= cost;
  state.plots[state.unlockedPlots].status = 'empty';
  state.unlockedPlots += 1;
  setTip(`成功解锁地块 ${state.unlockedPlots}。`);
  saveState();
  render();
}

function rest() {
  state.energy = Math.min(state.maxEnergy, state.energy + 8);
  setTip('休息了一会儿，恢复了 8 点体力。');
  saveState();
  render();
}

function bindTabs() {
  document.querySelectorAll('.tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach((tab) => tab.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach((tab) => tab.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
    });
  });
}

function render() {
  renderStats();
  renderFarm();
  renderSeeds();
  renderUpgrades();
  renderBag();
  const nextUnlockCost = state.unlockedPlots >= state.plots.length ? '已全部解锁' : `${150 + (state.unlockedPlots - 6) * 60} 金币`;
  els.unlockPlotBtn.textContent = `解锁地块（${nextUnlockCost}）`;
}

els.saveBtn.addEventListener('click', () => saveState(true));
els.unlockPlotBtn.addEventListener('click', unlockPlot);
els.restBtn.addEventListener('click', rest);

bindTabs();
setTip('先在右侧选择作物，再点击空地播种。成熟后点击地块即可收获。');
render();
setInterval(() => {
  renderStats();
  renderFarm();
}, 1000);
window.addEventListener('beforeunload', () => saveState(false));
