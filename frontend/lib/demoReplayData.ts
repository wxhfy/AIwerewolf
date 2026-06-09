export type DemoCamp = "village" | "wolf";

export interface DemoReplayPlayer {
  id: string;
  seat: number;
  name: string;
  role: string;
  camp: DemoCamp;
  mbti: string;
  style: string;
  aliveAtEnd: boolean;
  finalScore: number;
  processScore: number;
}

export interface DemoReplayStep {
  id: string;
  day: number;
  phaseLabel: string;
  kind: "talk" | "vote" | "attack" | "guard" | "witch_save" | "witch_poison" | "divine";
  kindLabel: string;
  actorId: string;
  targetId?: string;
  text: string;
  retrievalUsed: boolean;
  tokenTotal: number;
  latencyMs: number;
}

export const demoReplay = {
  source: {
    gameId: "9d0470c9-cdaa-4039-87bf-a59324a14b12",
    model: "doubao:ep-20260514115354-k4jz4",
    finishedAt: "2026-05-26 14:36",
    note: "历史真实 LLM 对局快照。该页面仅播放固定回放，不调用后端和模型。",
  },
  result: {
    winner: "village" as DemoCamp,
    winnerLabel: "好人阵营胜利",
    totalDays: 3,
    mvp: "南柯辞",
    mvpRole: "Seer",
    mvpScore: 55.4,
  },
  metrics: {
    decisions: 45,
    replaySteps: 18,
    retrievalHits: 36,
    retrievalRate: 0.8,
    totalTokens: 191855,
    avgLatencyMs: 19752,
  },
  players: [
    { id: "P1-492d47", seat: 1, name: "司南", role: "Hunter", camp: "village", mbti: "ISTP", style: "deconstructive", aliveAtEnd: true, finalScore: 47.1, processScore: 55.4 },
    { id: "P2-580f93", seat: 2, name: "舒朗", role: "Villager", camp: "village", mbti: "INFJ", style: "observer", aliveAtEnd: true, finalScore: 46.6, processScore: 54.8 },
    { id: "P3-6f9d14", seat: 3, name: "陶若安", role: "Guard", camp: "village", mbti: "ESFJ", style: "harmonizer", aliveAtEnd: false, finalScore: 47.4, processScore: 55.8 },
    { id: "P4-271f2c", seat: 4, name: "顾景行", role: "Werewolf", camp: "wolf", mbti: "INTP", style: "academic", aliveAtEnd: false, finalScore: 40.8, processScore: 47.9 },
    { id: "P5-3e75c8", seat: 5, name: "穆冬青", role: "Witch", camp: "village", mbti: "ESFJ", style: "caretaker", aliveAtEnd: false, finalScore: 47.5, processScore: 55.9 },
    { id: "P6-d8216c", seat: 6, name: "南柯辞", role: "Seer", camp: "village", mbti: "INFJ", style: "poetic", aliveAtEnd: false, finalScore: 55.4, processScore: 65.2 },
    { id: "P7-01a471", seat: 7, name: "云锦", role: "Werewolf", camp: "wolf", mbti: "ENFJ", style: "rallier", aliveAtEnd: false, finalScore: 45.3, processScore: 53.2 },
  ] satisfies DemoReplayPlayer[],
  chapters: [
    { label: "首夜查杀", stepIndex: 4, note: "预言家查验 7 号云锦为狼人，形成第一天主线。" },
    { label: "警徽竞选", stepIndex: 7, note: "猎人、狼人、女巫同时竞选，焦点集中到 7 号。" },
    { label: "第一天放逐", stepIndex: 11, note: "多名好人根据发言跟票行为归票 7 号。" },
    { label: "第二天误推出守卫", stepIndex: 15, note: "票型解释冲突扩大，守卫被放逐并留下 4 号狼面线索。" },
    { label: "女巫终局毒杀", stepIndex: 16, note: "女巫根据守卫遗言和票型逻辑毒杀最后一狼。" },
  ],
  evidence: [
    "Track B 将预言家查验、Day 1 归票和女巫关键毒杀列为高价值决策。",
    "Track C 在 36/45 次决策中注入可检索策略，覆盖率 80%。",
    "所有展示文本均来自同一局历史运行记录的固定快照，可重复复现。",
  ],
  steps: [
    { id: "step-01", day: 1, phaseLabel: "夜晚 · 守卫行动", kind: "guard", kindLabel: "守护", actorId: "P3-6f9d14", targetId: "P7-01a471", text: "首夜目前信息不足，狼队大概率优先刀能带队的好人，选偏号召型的玩家守护能降低好人损失。", retrievalUsed: false, tokenTotal: 2306, latencyMs: 11919 },
    { id: "step-02", day: 1, phaseLabel: "夜晚 · 狼人行动", kind: "attack", kindLabel: "袭击", actorId: "P4-271f2c", targetId: "P1-492d47", text: "目前信息不足，优先刀逻辑输出能力较强的玩家，降低好人阵营后续带队概率。", retrievalUsed: false, tokenTotal: 2628, latencyMs: 12946 },
    { id: "step-03", day: 1, phaseLabel: "夜晚 · 狼人行动", kind: "attack", kindLabel: "袭击", actorId: "P7-01a471", targetId: "P1-492d47", text: "我同意@4号:顾景行的判断，@1号:司南逻辑输出能力较强，刀掉他能降低好人阵营后续带队排狼的效率。", retrievalUsed: false, tokenTotal: 2764, latencyMs: 7640 },
    { id: "step-04", day: 1, phaseLabel: "夜晚 · 女巫行动", kind: "witch_save", kindLabel: "解药", actorId: "P5-3e75c8", targetId: "P1-492d47", text: "目前信息不足，首夜为避免好人损失轮次，选择救下被刀的@1号:司南，当前无明确狼人线索，暂不使用毒药。", retrievalUsed: true, tokenTotal: 2539, latencyMs: 7098 },
    { id: "step-05", day: 1, phaseLabel: "夜晚 · 预言家行动", kind: "divine", kindLabel: "查验", actorId: "P6-d8216c", targetId: "P7-01a471", text: "首轮优先查验高影响力的号召位，@7号:云锦的发言风格容易主导首日节奏，查验他能快速锚定阵营基准。", retrievalUsed: false, tokenTotal: 2387, latencyMs: 11689 },
    { id: "step-06", day: 1, phaseLabel: "警徽竞选发言", kind: "talk", kindLabel: "发言", actorId: "P1-492d47", text: "警徽我要，我是猎人，倒了能开枪自证，不会浪费好人轮次。\n\n我拿警徽就卡死所有人的发言逻辑，划水混票的直接进抗推位。\n\n今天先重点盯7号的警上发言，先标记测试。", retrievalUsed: true, tokenTotal: 2505, latencyMs: 15667 },
    { id: "step-07", day: 1, phaseLabel: "警徽竞选发言", kind: "talk", kindLabel: "发言", actorId: "P4-271f2c", text: "警徽我要，我记发言和票型的准确率很高，拿了警徽归票不会歪，浪费不了好人轮次。\n\n我现在60%倾向先重点盯7号，边角位藏身份的概率本来就比中置位高，等下他发言我会卡逻辑漏洞。", retrievalUsed: true, tokenTotal: 2877, latencyMs: 22111 },
    { id: "step-08", day: 1, phaseLabel: "警徽竞选发言", kind: "talk", kindLabel: "发言", actorId: "P5-3e75c8", text: "这把警徽我想拿哦，我记发言和票型都挺仔细的，拿到之后肯定会捋清楚逻辑再归票，不会浪费好人的轮次。\n\n刚才我看警上好多人一上来就把7号标成重点盯的对象，这有点奇怪吧？", retrievalUsed: true, tokenTotal: 2746, latencyMs: 15341 },
    { id: "step-09", day: 1, phaseLabel: "警徽投票", kind: "vote", kindLabel: "投票", actorId: "P6-d8216c", targetId: "P7-01a471", text: "我昨夜查验@7号:云锦为狼人，是确定的查杀目标，优先出他不会浪费好人轮次。接下来请好人重点观察此前无理由扎堆踩7的警上竞选者的发言破绽。", retrievalUsed: true, tokenTotal: 4956, latencyMs: 17796 },
    { id: "step-10", day: 1, phaseLabel: "白天自由发言", kind: "talk", kindLabel: "发言", actorId: "P7-01a471", text: "刚看到前面有人提主盯3号、备选挂5号，我觉得这个方向挺合理的，第一天信息少，先抓发言状态确实是最稳妥的切入点。\n\n3号等下正常聊就好，大大方方说你的判断就行。", retrievalUsed: true, tokenTotal: 2809, latencyMs: 21057 },
    { id: "step-11", day: 1, phaseLabel: "投票放逐", kind: "vote", kindLabel: "投票", actorId: "P1-492d47", targetId: "P7-01a471", text: "@7号:云锦无独立逻辑输出，全程照搬他人怀疑方向，狼面优先级最高。暂不投3、5号是因为二者均给出了明确判断，立场可追溯。", retrievalUsed: true, tokenTotal: 5025, latencyMs: 12638 },
    { id: "step-12", day: 1, phaseLabel: "投票放逐", kind: "vote", kindLabel: "投票", actorId: "P6-d8216c", targetId: "P7-01a471", text: "我是预言家，昨夜查验@7号:云锦为狼人，本轮优先出查杀。暂不投其他焦点位是因为暂无实锤佐证，后续好人可留意本轮票型里的异常跟风项。", retrievalUsed: true, tokenTotal: 5824, latencyMs: 12377 },
    { id: "step-13", day: 1, phaseLabel: "遗言", kind: "talk", kindLabel: "发言", actorId: "P7-01a471", text: "害，第一夜就吃刀我也是蛮懵的，我就是个没任何功能的平民，大家不用特意盘我身份哈。\n\n接下来我建议大家可以重点听3号的发言逻辑，目前没其他信息的话，就先把他当第一个怀疑锚点来核对就好。", retrievalUsed: true, tokenTotal: 3045, latencyMs: 28276 },
    { id: "step-14", day: 2, phaseLabel: "夜晚 · 女巫行动", kind: "witch_save", kindLabel: "解药", actorId: "P5-3e75c8", targetId: "P6-d8216c", text: "目前唯一起跳预言家的@6号:南柯辞属于关键神职，符合解药优先保神职的策略，我选择救下他；当前暂无百分百实锤的铁狼线索，毒药暂不使用。", retrievalUsed: true, tokenTotal: 4902, latencyMs: 15142 },
    { id: "step-15", day: 2, phaseLabel: "白天自由发言", kind: "talk", kindLabel: "发言", actorId: "P5-3e75c8", text: "我先把自己的票型捋得明明白白的啊，第一天我全程投的都是7号，从来没改票，也没踩过1号，怀疑我的朋友可以先核对下公开票型哈。\n\n现在3号和4号互咬得挺厉害的，我这轮重点就听你俩把各自的投票逻辑全聊透。", retrievalUsed: true, tokenTotal: 3734, latencyMs: 38584 },
    { id: "step-16", day: 2, phaseLabel: "遗言", kind: "talk", kindLabel: "发言", actorId: "P3-6f9d14", text: "我是守卫哦，这轮出局确实有点意外，不过好人轮次还够，大家别慌~\n\n第一天投票的时候4号顾景行单票挂6号南柯辞的票型我一直觉得很怪，狼面相对更高，大家可以多留意他的发言。", retrievalUsed: true, tokenTotal: 2998, latencyMs: 22633 },
    { id: "step-17", day: 3, phaseLabel: "夜晚 · 女巫行动", kind: "witch_poison", kindLabel: "毒药", actorId: "P5-3e75c8", targetId: "P4-271f2c", text: "解药已在首夜使用无法自救，@4号:顾景行被跳守卫出局的@3号:陶若安重点怀疑，且首日单票挂后被狼刀的好人@6号:南柯辞，狼面较高，选择撒毒。", retrievalUsed: true, tokenTotal: 5822, latencyMs: 33327 },
    { id: "step-18", day: 3, phaseLabel: "警徽移交", kind: "vote", kindLabel: "移交", actorId: "P5-3e75c8", targetId: "P1-492d47", text: "我首夜开解药救下了@1号:司南，他是明确的好人，之前也跳了猎人身份可信，警徽交给他带队我放心。", retrievalUsed: false, tokenTotal: 4084, latencyMs: 9339 },
  ] satisfies DemoReplayStep[],
};
