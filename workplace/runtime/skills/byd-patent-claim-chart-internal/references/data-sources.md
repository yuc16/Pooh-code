# 内网数据源说明

本 skill 只允许使用两个数据源：

- 大为专利
- 汽车之家

## 1. 大为专利

推荐访问方式：直接调用检索接口，而不是依赖网页搜索。

接口：

```text
POST https://pat.daweisoft.com/api/innojoy-search/api/v1/patent/search
```

常用请求头：

- `Content-Type: application/json;charset=UTF-8`
- `Origin: https://pat.daweisoft.com`
- `Referer: https://pat.daweisoft.com/searchresult`
- `X-Group-Env: PAT`
- `deviceId: <DAWEISOFT_DEVICE_ID>`
- `token: <DAWEISOFT_TOKEN>`

说明：

- `token` 和 `deviceId` 来自浏览器登录态，可能过期
- 如果内网环境要求代理，应复用用户现有代理设置

### 1.1 检索候选专利

用途：按关键词或主题词拉候选专利列表。

关键参数：

- `query`
- `oriQuery`
- `pageNum`
- `pageSize`
- `fields`
- `searchType = patent_list`

在本 skill 里，这一步必须附带硬约束：

- `CAS=(比亚迪)`
- `CC=(CN)`

建议查询形态：

```text
(<关键词>) AND CAS=(比亚迪) AND CC=(CN)
```

建议返回字段：

```text
PTS,DPIStar,PNM,TI,CLS,PA,AN,AD,INN,CC,CAS,AB,APD,APN
```

### 1.2 按公开号拉权利要求全文

用途：已知专利公开号时，精确拉取权利要求。

关键参数：

- `query = PNM=<专利公开号>`
- `oriQuery = PNM=<专利公开号>`
- `pageNum = 1`
- `pageSize = 1`
- `fields = PNM,TI,PA,CAS,INN,AD,CC,CLS,CLMN,CLM,CL`
- `searchType = baseinfo_detail`

关键点：

- 要拿权利要求全文，`searchType` 必须是 `baseinfo_detail`
- 中文权利要求优先读 `CL.CLZH`
- 原文字段可读 `CL.CLOL`
- 如果返回的是 XML 片段，先剥离标签再使用

## 2. 汽车之家

推荐访问方式：直接调用结构化接口和车型页数据，不依赖外部搜索引擎。

### 2.1 新能源月销榜

接口：

```text
GET https://www.autohome.com.cn/web-main/car/rank/getList
```

常见参数：

- `date`
- `pageindex`
- `pagesize`
- `energytype`
- `typeid`

用途：

- 先筛出候选车系
- 获取 `seriesid`
- 获取销量、车系名、价格区间等信息

### 2.2 车系页

页面：

```text
GET https://www.autohome.com.cn/{series_id}
```

用途：

- 从 `__NEXT_DATA__` 中取基础信息
- 获取代表车型 `hotSpecId`
- 获取车系名、品牌名、厂商名、级别等

### 2.3 参数接口

接口：

```text
GET https://www.autohome.com.cn/web-main/car/param/getParamConf
```

关键参数：

- `mode = 1`
- `site = 2`
- `specid = <hotSpecId>`

适合优先抽取的字段：

- 能源类型
- 电池类型
- 电芯品牌
- 电池能量(kWh)
- 电池能量密度(Wh/kg)
- CLTC纯电续航里程(km)
- 百公里耗电量(kWh/100km)
- 快充功能
- 电池快充时间(小时)
- 电池慢充时间(小时)

## 3. 在本 skill 中的推荐用法

建议按以下顺序：

1. 如果只给主题词，先用大为接口检索“比亚迪中文有权专利”
2. 再按公开号精确拉目标专利的权利要求
3. 用汽车之家月销榜或指定车系页筛候选竞品
4. 用车型页和参数接口提取可用于比对的公开特征
5. 把结果落入 `.xlsx`

## 4. 证据边界

- 证据链接只能来自大为专利或汽车之家
- 没有证据就写 `证据不足`
- 不要把模型推断包装成站点已明示公开的信息
