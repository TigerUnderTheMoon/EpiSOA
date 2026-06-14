======================================================================
CASE STUDY: E001
======================================================================

Event: 广州市白云区三元里村城中村改造补偿安置方案发布事件
Domain: urban_renewal
Location: 广州市, 广东省
Time: 2025-01-07 ~ 2025-01-11
Trigger: 白云区政府印发三元里村城中村改造项目土地及房屋征收补偿安置方案
Evidence: 35 items | Gold tuples: 4 | Gold chains: 3

--- GOLD STAKEHOLDER OPINIONS ---
  [三元里村村民] 总体上同意城中村改造，但对补偿安置方案的支持率偏低，存在诉求和不满
    Sentiment: mixed  Evidence: ['ev-00023', 'ev-00010']
  [广州市白云区政府] 发布补偿安置方案，确保安置房全部回迁至改造范围内，并遵循‘拆一补一’原则
    Sentiment: positive  Evidence: ['ev-00001', 'ev-00002']
  [对改造持积极态度的村民] 对征拆工作组进驻感到振奋，并主动前往咨询征收事宜
    Sentiment: positive  Evidence: ['ev-00010']
  [对补偿方案不满的村民] 仅33.62%的村民支持拆迁补偿方案，多数人可能对补偿标准不满
    Sentiment: negative  Evidence: ['ev-00023']

--- GOLD EVENT CHAINS ---
  Chain 1 (CHAIN_E001_001):
    Stage 1: 白云区政府印发三元里村城中村改造补偿安置方案
    Stage 2: 村民对补偿方案支持率仅33.62%，引发争议
    Stage 3: 政府解释“拆一补一”原则及回迁安置细节
    Stage 4: 白云区成立13个征收工作组进驻三元里村，启动征拆
    Evidence: ['ev-00001', 'ev-00029', 'ev-00023', 'ev-00007', 'ev-00008', 'ev-00010']
  Chain 2 (CHAIN_E001_002):
    Stage 1: 三元里村城中村改造补偿安置方案发布
    Stage 2: 居民同意改造率超80%，但补偿方案支持率低
    Stage 3: 2025年5月发布“村改居独栋村居类型”住宅房屋扶助方案征求意见稿
    Stage 4: 2025年6月发布旧村地块国有土地上房屋征收补偿补充方案征求意见稿
    Evidence: ['ev-00001', 'ev-00023', 'ev-00018', 'ev-00013']
  Chain 3 (CHAIN_E001_003):
    Stage 1: 方案发布后引发社会关注
    Stage 2: 部分居民对安置和补偿标准提出质疑
    Stage 3: 政府组织征收工作组进驻，开展政策咨询和签约
    Stage 4: 改造项目按计划推进
    Evidence: ['ev-00010', 'ev-00015', 'ev-00023', 'ev-00001']

--- PREDICTED EVENT CHAINS ---
  Chain 1:
    Stage 1: 补偿安置方案发布
    Stage 2: 方案引起媒体广泛报道和社会关注
    Stage 3: 政府发布征求意见稿和补充方案回应居民诉求
    Stage 4: 征收工作组进驻并推出签约激励政策推动实施
    Evidence: ['ev-00001', 'ev-00002', 'ev-00003', 'ev-00005', 'ev-00006', 'ev-00013']
  Chain 2:
    Stage 1: 补偿安置方案发布
    Stage 2: 居民对补偿方案支持率低引发争议
    Stage 3: 政府出台村改居独栋村居类型扶助方案征求意见
    Stage 4: 征收工作组进驻启动征拆工作
    Evidence: ['ev-00001', 'ev-00004', 'ev-00023', 'ev-00014', 'ev-00018', 'ev-00010']
  Chain 3:
    Stage 1: 补偿安置方案发布
    Stage 2: 方案在主流媒体和社交媒体广泛扩散
    Stage 3: 政府发布补充方案和扶助方案完善补偿体系
    Stage 4: 签约奖励政策出台激励提前签约
    Stage 5: 居民同意改造比率超过80%项目推进取得进展
    Evidence: ['ev-00007', 'ev-00008', 'ev-00003', 'ev-00021', 'ev-00013', 'ev-00014']

--- CHAIN EVIDENCE OVERLAP ---
  Gold evidence: 9
  Pred evidence: 15
  Overlap: 7 (78%)
  Gold-only evidence IDs: ['ev-00015', 'ev-00029']
  Pred-only evidence IDs: ['ev-00002', 'ev-00003', 'ev-00004', 'ev-00005', 'ev-00006', 'ev-00014', 'ev-00021', 'ev-00022']

--- EVIDENCE SOURCE DIVERSITY ---
  mainstream_news: 14
  official: 11
  public_web: 6
  social_media: 3
  public_interaction: 1

--- PREDICTED TUPLES vs GOLD ---
  [PRED: 广州市白云区政府] 认为补偿安置方案合理，支持改造，提供回迁安置和奖励激励
    Sentiment: positive  Evidence: ['ev-00001', 'ev-00002', 'ev-00022']
  [PRED: 三元里村支持改造的村民] 对改造方案感到振奋，积极签约并享受奖励，支持改造
    Sentiment: positive  Evidence: ['ev-00010', 'ev-00022']
  [PRED: 三元里村对补偿方案不满的村民] 认为补偿方案不合理，支持率低，需要调整
    Sentiment: negative  Evidence: ['ev-00023']

--- DIAGNOSTICS ---
  Pred tuples: 3  Gold tuples: 4
  Pred chains: 3  Gold chains: 3

======================================================================
CASE STUDY: E003
======================================================================

Event: 深圳市罗湖区金钻豪园旧改过渡安置费拖欠事件
Domain: urban_renewal
Location: 深圳市, 广东省
Time: 2024-09-11 ~ 2024-09-11
Trigger: 原业主集中反映旧改项目过渡安置费未按约支付
Evidence: 33 items | Gold tuples: 3 | Gold chains: 3

--- GOLD STAKEHOLDER OPINIONS ---
  [原业主（拆迁户）] 对开发商长期拖欠过渡安置费表示强烈不满和担心，要求尽快支付所欠款项
    Sentiment: negative  Evidence: ['ev-00056', 'ev-00060', 'ev-01438']
  [原业主（拆迁户）] 对过渡安置费被长期拖欠感到无助和愤怒，多次前往开发商和街道办事处反应问题但未解决
    Sentiment: negative  Evidence: ['ev-01438']
  [罗湖区翠竹街道办事处] 对金钻豪园旧改项目资金和盘活问题持续关注，积极协调引入中信城开等新合作方以推动问题解决
    Sentiment: positive  Evidence: ['ev-01440', 'ev-01436']

--- GOLD EVENT CHAINS ---
  Chain 1 (CHAIN_E003_001):
    Stage 1: 开发商拖欠金钻豪园业主过渡安置费
    Stage 2: 业主向街道办事处及相关部门反映问题
    Stage 3: 官方回应正在协调解决资金和项目盘活方案
    Stage 4: 引入中信联合体签署盘活合作协议，解决安置费问题
    Evidence: ['ev-00056', 'ev-01438', 'ev-00059', 'ev-01440']
  Chain 2 (CHAIN_E003_002):
    Stage 1: 金钻豪园旧改项目自2005年启动，经历多次波折
    Stage 2: 楼市下行导致项目停工，过渡费长期拖欠
    Stage 3: 罗湖区翠竹街道及区级部门介入协调
    Stage 4: 2025年项目获用地批复，盘活协议签订
    Evidence: ['ev-01439', 'ev-01435', 'ev-00059', 'ev-01436']
  Chain 3 (CHAIN_E003_003):
    Stage 1: 拆迁户反映2022年过渡安置费未支付
    Stage 2: 居民多次咨询开发商和街道无果
    Stage 3: 新闻媒体报道揭露多项目过渡费拖欠困局
    Stage 4: 官方推动引入国企盘活项目，最终达成协议
    Evidence: ['ev-00056', 'ev-01438', 'ev-00057', 'ev-01440']

--- PREDICTED EVENT CHAINS ---
  Chain 1:
    Stage 1: 过渡安置费长期拖欠，业主多次反映未获支付
    Stage 2: 业主通过社交媒体和论坛投诉，引发舆论关注
    Stage 3: 开发商资金紧张，项目停工，冲突加剧
    Stage 4: 罗湖区街道和区级部门回应，表示将协调并尝试引入国企盘活项目
    Stage 5: 项目后续取得用地批复，但整体进展缓慢
    Evidence: ['ev-00056', 'ev-00057', 'ev-00058', 'ev-00059', 'ev-01436']
  Chain 2:
    Stage 1: 金钻豪园旧改项目自2005年启动，过渡安置费拖欠问题长期存在
    Stage 2: 楼市下行，开发商资金链断裂，拖欠安置费问题扩散
    Stage 3: 业主向开发商和街道办事处咨询无果，矛盾激化
    Stage 4: 官方逐步协调，但引入国企盘活方案进展有限
    Evidence: ['ev-01439', 'ev-01435', 'ev-00061', 'ev-01438']

--- CHAIN EVIDENCE OVERLAP ---
  Gold evidence: 8
  Pred evidence: 9
  Overlap: 7 (88%)
  Gold-only evidence IDs: ['ev-01440']
  Pred-only evidence IDs: ['ev-00058', 'ev-00061']

--- EVIDENCE SOURCE DIVERSITY ---
  mainstream_news: 10
  official: 7
  public_web: 5
  forum: 5
  public_interaction: 4
  social_media: 2

--- PREDICTED TUPLES vs GOLD ---
  [PRED: 金钻豪园原业主（拆迁户）] 过渡安置费被长期拖欠，开发商未按约支付，项目停工导致生活困难
    Sentiment: negative  Evidence: ['ev-00056', 'ev-00060', 'ev-01438']
  [PRED: 金钻豪园开发商（深圳新华城房地产有限公司）] 公司资金充足但深圳新房市场价格战激烈，销售去化慢，即使建好也难卖，因此放慢项目进度，导致过渡费拖欠
    Sentiment: mixed  Evidence: ['ev-00058']
  [PRED: 深圳市罗湖区翠竹街道办事处及相关部门] 官方正在逐步协调解决过渡费拖欠问题，试图引入国企盘活项目，但进展缓慢
    Sentiment: mixed  Evidence: ['ev-00059', 'ev-00061']

--- DIAGNOSTICS ---
  Pred tuples: 3  Gold tuples: 3
  Pred chains: 2  Gold chains: 3

======================================================================
CASE STUDY: E018
======================================================================

Event: 暨南大学石牌校区宿舍霉菌与甲醛争议事件
Domain: education
Location: 广州市, 广东省
Time: 2024-07-13 ~ 2024-07-18
Trigger: 学生搬入宿舍后集中反映霉菌和空气质量问题
Evidence: 35 items | Gold tuples: 4 | Gold chains: 3

--- GOLD STAKEHOLDER OPINIONS ---
  [暨南大学学生] 反映宿舍霉菌遍布、甲醛超标，导致皮肤过敏、头晕等健康问题，要求学校解决宿舍环境问题
    Sentiment: negative  Evidence: ['ev-01658', 'ev-01654', 'ev-00439']
  [暨南大学党委宣传部] 表示学校已进行走访调查并收集意见，正在处理宿舍问题
    Sentiment: neutral  Evidence: ['ev-00437', 'ev-01653']
  [暨南大学校方] 建议学生暂时克服困难或回家等待，无法全面满足更换设施的请求
    Sentiment: negative  Evidence: ['ev-01651']
  [媒体] 指出暨南大学宿舍问题暴露管理困境，质疑校方应对不力
    Sentiment: negative  Evidence: ['ev-00445']

--- GOLD EVENT CHAINS ---
  Chain 1 (CHAIN_E018_001):
    Stage 1: 学生搬入宿舍后反映霉菌遍布、甲醛超标
    Stage 2: 学生社交媒体发声，媒体介入报道
    Stage 3: 校方党委宣传部表示正在处理，但未提具体方案
    Stage 4: 问题未解决，学生继续忍受或回家等待
    Evidence: ['ev-01658', 'ev-00437', 'ev-00443']
  Chain 2 (CHAIN_E018_002):
    Stage 1: 学生出现皮肤过敏、发烧住院等健康问题
    Stage 2: 学生怀疑甲醛超标，要求校方解决
    Stage 3: 校方走访调查但表示无法立即提供解决方案，建议学生克服或回家
    Stage 4: 部分学生选择暂不入住
    Evidence: ['ev-00439', 'ev-01651']
  Chain 3 (CHAIN_E018_003):
    Stage 1: 2024年7月中旬学生集中投诉宿舍环境
    Stage 2: 潮新闻记者于7月17日致电校方宣传部
    Stage 3: 校方回应表示已关注并收集意见，后续无明确整改
    Stage 4: 事件在网络上持续发酵，舆论关注
    Evidence: ['ev-00440', 'ev-01653']

--- PREDICTED EVENT CHAINS ---
  Chain 1:
    Stage 1: trigger: 暨南大学学生通过社交媒体曝光宿舍霉菌、甲醛超标及设施老化问题
    Stage 2: diffusion: 多家主流媒体报道此事，引发社会广泛关注
    Stage 3: response: 校方表示正在跟进处理，但未给出具体解决方案
    Stage 4: follow_up: 学生反映问题未得到实质性解决，只能继续忍受恶劣环境
    Evidence: ['ev-00438', 'ev-00440', 'ev-01652', 'ev-00441', 'ev-01657']
  Chain 2:
    Stage 1: trigger: 学生报告因宿舍甲醛超标出现皮肤过敏、发烧住院等健康问题
    Stage 2: conflict: 学生与校方之间矛盾激化，学生质疑校方管理失职
    Stage 3: response: 校方走访调查后反馈无法提供解决方案，建议学生暂时克服或回家
    Stage 4: resolution: 校方未能有效解决问题，事件陷入僵局
    Evidence: ['ev-00439', 'ev-00441', 'ev-01651', 'ev-01658']
  Chain 3:
    Stage 1: trigger: 学生社交媒体发帖揭露宿舍霉菌和甲醛问题
    Stage 2: diffusion: 舆论持续发酵，多家媒体跟进报道并探讨背后管理困境
    Stage 3: response: 校方党委宣传部回应称正在处理，但实际效果不佳
    Stage 4: follow_up: 舆论压力下，校方未进一步公布整改措施，事件逐渐平息但未彻底解决
    Evidence: ['ev-00437', 'ev-00442', 'ev-00443', 'ev-01654']

--- CHAIN EVIDENCE OVERLAP ---
  Gold evidence: 7
  Pred evidence: 12
  Overlap: 6 (86%)
  Gold-only evidence IDs: ['ev-01653']
  Pred-only evidence IDs: ['ev-00438', 'ev-00441', 'ev-00442', 'ev-01652', 'ev-01654', 'ev-01657']

--- EVIDENCE SOURCE DIVERSITY ---
  mainstream_news: 15
  social_media: 9
  official: 8
  forum: 3

--- PREDICTED TUPLES vs GOLD ---
  [PRED: 暨南大学学生] 宿舍霉菌遍布、甲醛超标、设施破损，导致皮肤过敏、发烧住院等健康问题，校方处理不力，学生被迫忍受恶劣环境。
    Sentiment: negative  Evidence: ['ev-00437', 'ev-00439', 'ev-00440', 'ev-00441']
  [PRED: 暨南大学校方（党委宣传部）] 学校已收到投诉并正在进行走访调查收集意见，但当前无法提供明确解决方案，建议学生暂时克服困难或回家等待。
    Sentiment: mixed  Evidence: ['ev-00437', 'ev-00440', 'ev-01651', 'ev-01652']
  [PRED: 关注此事的网民和公众] 对暨南大学宿舍环境表示强烈不满，批评校方管理不善，呼吁改善宿舍条件。
    Sentiment: negative  Evidence: ['ev-00438', 'ev-00443', 'ev-00444', 'ev-01657']

--- DIAGNOSTICS ---
  Pred tuples: 3  Gold tuples: 4
  Pred chains: 3  Gold chains: 3
