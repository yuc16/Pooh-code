const crops = {
  carrot: { name: '月胡萝卜', icon: '🥕', cost: 6, days: 2, value: 16, waterNeed: 1 },
  strawberry: { name: '霓虹果莓', icon: '🍓', cost: 10, days: 3, value: 26, waterNeed: 2 },
  pumpkin: { name: '琥珀南瓜', icon: '🎃', cost: 18, days: 4, value: 46, waterNeed: 2 },
  grape: { name: '夜露葡萄', icon: '🍇', cost: 24, days: 5, value: 64, waterNeed: 3 },
};

const seasons = ['春', '夏', '秋', '冬'];
const weatherTypes = [
  { name: '晴朗', energyBonus: 0, growthBonus: 0, rainChance: 0 },
  { name: '微风', energyBonus: 1, growthBonus: 0, rainChance: 0 },
  { name: '细雨', energyBonus: 0, growthBonus: 1, rainChance: 1 },
  { name: '流星夜', energyBonus: 2, growthBonus: 1, rainChance: 0 },
];

const state = {
  coins: 36,
  energy: 8,
  maxEnergy: 8,
  day: 1,
  seasonIndex: 0,
  selectedSeed: 'carrot',
  weather: weatherTypes[0],
  autoHarvestLevel: 0,
  inventory: {
    carrot: 0,
    strawberry: 0,
    pumpkin: 0,
    grape: 0,
  },
  plots: Array.from({ length: 12 }, () => ({
    cropKey: null,
    plantedDay: null,
    growth: 0,
    wateredToday: false,
    ready: false,
  })),
  logs: [],
};

const els = {
  coins: document.querySelector('#coins'),
  energy: document.querySelector('#energy'),
  day: document.querySelector('#day'),
  weather: document.querySelector('#weather'),
  season: document.querySelector('#season'),
  seedList: document.querySelector('#seedList'),
  inventory: document.querySelector('#inventory'),
  shopList: document.querySelector('#shopList'),
  logList: document.querySelector('#logList'),
  farmGrid: document.querySelector('#farmGrid'),
  plotTemplate: document.querySelector('#plotTemplate'),
  sleepBtn: document.querySelector('#sleepBtn'),
  waterAllBtn: document.querySelector('#waterAllBtn'),
};

const shopItems = [
  {
    id: 'energy-up',
    name: '提灯背包',
    desc: '最大能量 +2，第二天开始更耐劳。',
    cost: () => 30 + (state.maxEnergy - 8) * 12,
    buy: () => {
      state.maxEnergy += 2;
      state.energy += 2;
      addLog('你买下提灯背包，今天能多做两件事。');
    },
  },
  {
    id: 'auto-harvest',
    name: '星萤小帮手',
    desc: '每天开始时自动收割 1 块成熟土地。',
    cost: () => 60 + state.autoHarvestLevel * 40,
    buy: () => {
      state.autoHarvestLevel += 1;
      addLog(`星萤小帮手增加到 Lv.${state.autoHarvestLevel}。`);
    },
  },
  {
    id: 'bonus-coins',
    name: '月集订单',
    desc: '立刻获得一笔现金流。',
    cost: () => 18,
    buy: () => {
      state.coins += 30;
      addLog('你完成了一份月集订单，立刻到账 30 金币。');
    },
  },
];

function randomWeather() {
  return weatherTypes[Math.floor(Math.random() * weatherTypes.length)];
}

function addLog(text) {
  state.logs.unshift({ text, time: `第 ${state.day} 天` });
  state.logs = state.logs.slice(0, 12);
}

function spendEnergy(amount) {
  if (state.energy < amount) {
    addLog('体力不足，先睡到下一天恢复精力。');
    return false;
  }
  state.energy -= amount;
  return true;
}

function selectSeed(seedKey) {
  state.selectedSeed = seedKey;
  renderSeeds();
}

function plantSeed(plotIndex) {
  const plot = state.plots[plotIndex];
  const crop = crops[state.selectedSeed];
  if (plot.cropKey) {
    return waterOrHarvest(plotIndex);
  }
  if (state.coins < crop.cost) {
    return addLog(`${crop.name} 种子不够钱了。`);
  }
  if (!spendEnergy(1)) return;
  state.coins -= crop.cost;
  Object.assign(plot, {
    cropKey: state.selectedSeed,
    plantedDay: state.day,
    growth: 0,
    wateredToday: false,
    ready: false,
  });
  addLog(`你在 ${plotIndex + 1} 号土地播下了${crop.name}。`);
  render();
}

function waterOrHarvest(plotIndex) {
  const plot = state.plots[plotIndex];
  if (!plot.cropKey) return;
  const crop = crops[plot.cropKey];
  if (plot.ready) {
    if (!spendEnergy(1)) return;
    harvestPlot(plotIndex);
    return;
  }
  if (plot.wateredToday) {
    addLog(`${crop.name} 今天已经浇过水了。`);
    return;
  }
  if (!spendEnergy(1)) return;
  plot.wateredToday = true;
  plot.growth += 1;
  if (plot.growth >= crop.days + crop.waterNeed - 1) {
    plot.ready = true;
    addLog(`${crop.name} 在夜色里成熟了，可以收获。`);
  } else {
    addLog(`你给 ${crop.name} 浇了水，长势更好了。`);
  }
  render();
}

function harvestPlot(plotIndex, auto = false) {
  const plot = state.plots[plotIndex];
  if (!plot.cropKey || !plot.ready) return;
  const crop = crops[plot.cropKey];
  state.inventory[plot.cropKey] += 1;
  state.coins += crop.value;
  state.plots[plotIndex] = {
    cropKey: null,
    plantedDay: null,
    growth: 0,
    wateredToday: false,
    ready: false,
  };
  addLog(`${auto ? '星萤小帮手' : '你'}收获了 ${crop.name}，卖出获得 ${crop.value} 金币。`);
  render();
}

function nextDay() {
  state.day += 1;
  state.seasonIndex = Math.floor((state.day - 1) / 4) % seasons.length;
  state.weather = randomWeather();
  state.energy = state.maxEnergy + state.weather.energyBonus;

  let autoHarvests = state.autoHarvestLevel;
  state.plots.forEach((plot, index) => {
    if (!plot.cropKey) return;

    if (plot.ready && autoHarvests > 0) {
      autoHarvests -= 1;
      harvestPlot(index, true);
      return;
    }

    plot.wateredToday = false;
    plot.growth += 1 + state.weather.growthBonus + state.weather.rainChance;
    const crop = crops[plot.cropKey];
    if (plot.growth >= crop.days + crop.waterNeed - 1) {
      plot.ready = true;
    }
  });

  addLog(`新的一天开始了：${state.weather.name}。体力恢复到 ${state.energy}。`);
  render();
}

function waterAll() {
  const dryPlots = state.plots
    .map((plot, index) => ({ plot, index }))
    .filter(({ plot }) => plot.cropKey && !plot.ready && !plot.wateredToday);

  if (!dryPlots.length) {
    addLog('今天没有需要统一浇水的土地。');
    render();
    return;
  }

  dryPlots.forEach(({ index }) => {
    if (state.energy <= 0) return;
    waterOrHarvest(index);
  });
}

function buyShopItem(item) {
  const cost = item.cost();
  if (state.coins < cost) {
    addLog(`金币不足，买不了 ${item.name}。`);
    render();
    return;
  }
  state.coins -= cost;
  item.buy();
  render();
}

function renderSeeds() {
  els.seedList.innerHTML = Object.entries(crops)
    .map(([key, crop]) => `
      <button class="seed-item ${state.selectedSeed === key ? 'active' : ''}" data-seed="${key}">
        <div>
          <strong>${crop.icon} ${crop.name}</strong>
          <div class="plot-meta">${crop.days} 天成熟 · 售价 ${crop.value}</div>
        </div>
        <span class="seed-price">${crop.cost} 金币</span>
      </button>
    `)
    .join('');

  els.seedList.querySelectorAll('[data-seed]').forEach((button) => {
    button.addEventListener('click', () => selectSeed(button.dataset.seed));
  });
}

function renderInventory() {
  els.inventory.innerHTML = Object.entries(crops)
    .map(([key, crop]) => `
      <div class="inventory-item">
        <div>
          <strong>${crop.icon} ${crop.name}</strong>
          <div class="plot-meta">累计收获</div>
        </div>
        <span class="inventory-value">${state.inventory[key]} 份</span>
      </div>
    `)
    .join('');
}

function renderShop() {
  els.shopList.innerHTML = shopItems
    .map((item) => {
      const cost = item.cost();
      return `
        <div class="shop-item">
          <div>
            <strong>${item.name}</strong>
            <div>${item.desc}</div>
            <div class="plot-meta">价格 ${cost} 金币</div>
          </div>
          <button type="button" data-shop="${item.id}" ${state.coins < cost ? 'disabled' : ''}>购买</button>
        </div>
      `;
    })
    .join('');

  els.shopList.querySelectorAll('[data-shop]').forEach((button) => {
    const item = shopItems.find((entry) => entry.id === button.dataset.shop);
    button.addEventListener('click', () => buyShopItem(item));
  });
}

function renderLogs() {
  els.logList.innerHTML = state.logs
    .map((log) => `
      <div class="log-item">
        <span>${log.text}</span>
        <time>${log.time}</time>
      </div>
    `)
    .join('');
}

function renderPlots() {
  els.farmGrid.innerHTML = '';
  state.plots.forEach((plot, index) => {
    const node = els.plotTemplate.content.firstElementChild.cloneNode(true);
    const crop = plot.cropKey ? crops[plot.cropKey] : null;
    const progress = crop ? Math.min(100, (plot.growth / (crop.days + crop.waterNeed - 1)) * 100) : 0;
    node.dataset.state = plot.cropKey ? 'growing' : 'empty';
    node.dataset.ready = String(plot.ready);
    node.querySelector('.plot-weather').textContent = plot.ready
      ? '可收获'
      : plot.cropKey
        ? plot.wateredToday ? '已浇水' : '待照料'
        : `土地 #${index + 1}`;
    node.querySelector('.plot-name').textContent = crop ? `${crop.icon} ${crop.name}` : '空地';
    node.querySelector('.plot-meta').textContent = crop
      ? plot.ready
        ? `点击收获 · 售价 ${crop.value}`
        : `成长 ${Math.floor(progress)}%`
      : '点击播种';
    node.querySelector('.plot-progress i').style.width = `${progress}%`;
    node.addEventListener('click', () => plantSeed(index));
    els.farmGrid.appendChild(node);
  });
}

function renderStats() {
  els.coins.textContent = state.coins;
  els.energy.textContent = `${state.energy}/${state.maxEnergy}`;
  els.day.textContent = state.day;
  els.weather.textContent = state.weather.name;
  els.season.textContent = seasons[state.seasonIndex];
}

function render() {
  renderStats();
  renderSeeds();
  renderInventory();
  renderShop();
  renderLogs();
  renderPlots();
}

els.sleepBtn.addEventListener('click', nextDay);
els.waterAllBtn.addEventListener('click', waterAll);

addLog('庄园开张了。先选一种种子，再点土地开始耕作。');
render();
