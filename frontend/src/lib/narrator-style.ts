export const SINGLE_NARRATOR_STYLE_PRESET_SETTING_MAP: Record<string, string> = {
  幽默: '风格幽默诙谐，多用调侃和玩梗的方式呈现内容，让观众在轻松愉快中获取信息',
  犀利: '风格犀利直接，一针见血地指出问题本质，观点鲜明，措辞有力但不失理性',
  理性: '风格冷静客观，以理性分析和逻辑推演为主，用数据和事实说话，避免情绪化表达',
  讽刺: '风格辛辣讽刺，善用反讽和夸张手法揭示荒诞现实，语言机智尖锐但不恶毒',
  正经: '风格严肃正经，以专业严谨的态度解读事件，措辞规范得体，适合正式场合传播',
  出奇: '风格出奇制胜，善于从意想不到的角度切入内容，提出独特见解，语言新颖有创意，能引发观众兴趣和讨论',
  批判: '风格批判犀利，敢于揭露问题的阴暗面，观点鲜明有力，语言尖锐但不失理性，适合对社会现象进行深度剖析',
}

export const SINGLE_NARRATOR_STYLE_PRESET_NAME_MAP: Record<string, string> = {
  幽默: '范德彪',
  犀利: '李云龙',
  理性: '梅长苏',
  讽刺: '纪晓岚',
  正经: '海瑞',
  出奇: '李逍遥',
  批判: '侯亮平',
}

export const SINGLE_DEFAULT_NARRATOR_STYLE = '幽默'
export const SINGLE_CUSTOM_NARRATOR_NAME = '讲述者'

export const SINGLE_NARRATOR_STYLE_OPTIONS = [
  { value: '__default__', label: '自定义' },
  { value: '幽默', label: '幽默' },
  { value: '犀利', label: '犀利' },
  { value: '理性', label: '理性' },
  { value: '讽刺', label: '讽刺' },
  { value: '正经', label: '正经' },
  { value: '出奇', label: '出奇' },
  { value: '批判', label: '批判' },
] as const

export const DUO_DEFAULT_NARRATOR_STYLE = '双讲拆解型'
export const DUO_CUSTOM_NARRATOR_NAMES = ['讲述者1', '讲述者2'] as const

export const DUO_NARRATOR_STYLE_OPTIONS = [
  { value: '__default__', label: '自定义' },
  { value: '双讲拆解型', label: '双讲拆解型' },
  { value: '辩论对抗型', label: '辩论对抗型' },
  { value: '评论解读型', label: '评论解读型' },
  { value: '“主持人 + 专家”拆解型', label: '“主持人 + 专家”拆解型' },
  { value: '“主讲 + 捧哏”喜剧型', label: '“主讲 + 捧哏”喜剧型' },
  { value: '互怼吐槽型（损友感）', label: '互怼吐槽型（损友感）' },
  { value: '访谈挖掘型（采访感）', label: '访谈挖掘型（采访感）' },
  { value: '复盘推理型', label: '复盘推理型' },
  { value: '“共情陪伴”疗愈型', label: '“共情陪伴”疗愈型' },
] as const

export interface DuoNarratorPresetSettings {
  role_1: string
  role_2: string
}

export interface DuoNarratorPresetNames {
  role_1: string
  role_2: string
}

export interface DuoNarratorPresetAppearances {
  role_1: string
  role_2: string
}

export interface DuoNarratorPresetVoices {
  role_1: NarratorPresetVoiceProfile
  role_2: NarratorPresetVoiceProfile
}

export interface NarratorPresetVoiceProfile {
  voice_audio_provider: 'edge_tts' | 'wan2gp' | 'volcengine_tts' | 'kling_tts' | 'vidu_tts' | 'minimax_tts' | 'xiaomi_mimo_tts'
  voice_name: string
  voice_speed?: number
  voice_wan2gp_preset?: string
  voice_wan2gp_alt_prompt?: string
  voice_wan2gp_audio_guide?: string
  voice_wan2gp_temperature?: number
  voice_wan2gp_top_k?: number
  voice_wan2gp_seed?: number
}

export interface DuoNarratorPresetImageAssets {
  role_1: string
  role_2: string
}

const SINGLE_NARRATOR_EDGE_CUSTOM_VOICE: NarratorPresetVoiceProfile = {
  voice_audio_provider: 'edge_tts',
  voice_name: 'zh-CN-YunjianNeural',
  voice_speed: 1.3,
}

const DUO_NARRATOR_EDGE_CUSTOM_ROLE_1_VOICE: NarratorPresetVoiceProfile = {
  voice_audio_provider: 'edge_tts',
  voice_name: 'zh-CN-YunjianNeural',
  voice_speed: 1.3,
}

const DUO_NARRATOR_EDGE_CUSTOM_ROLE_2_VOICE: NarratorPresetVoiceProfile = {
  voice_audio_provider: 'edge_tts',
  voice_name: 'zh-CN-XiaoyiNeural',
  voice_speed: 1.3,
}

const EDGE_VOICE_MALE_1 = 'zh-CN-YunjianNeural'
const EDGE_VOICE_MALE_2 = 'zh-CN-YunxiNeural'
const EDGE_VOICE_FEMALE_1 = 'zh-CN-XiaoyiNeural'
const EDGE_VOICE_FEMALE_2 = 'zh-CN-XiaoxiaoNeural'

type CharacterGender = 'male' | 'female'

const CHARACTER_GENDER_MAP: Record<string, CharacterGender> = {
  范德彪: 'male',
  李云龙: 'male',
  梅长苏: 'male',
  纪晓岚: 'male',
  海瑞: 'male',
  李逍遥: 'male',
  侯亮平: 'male',
  包拯: 'male',
  公孙策: 'male',
  高启强: 'male',
  安欣: 'male',
  李达康: 'male',
  沙瑞金: 'male',
  唐仁: 'male',
  秦风: 'male',
  白展堂: 'male',
  郭芙蓉: 'female',
  宁采臣: 'male',
  燕赤霞: 'male',
  汪淼: 'male',
  叶文洁: 'female',
  狄仁杰: 'male',
  李元芳: 'male',
  小龙女: 'female',
  杨过: 'male',
}

function buildEdgePresetVoice(voiceName: string): NarratorPresetVoiceProfile {
  return {
    voice_audio_provider: 'edge_tts',
    voice_name: voiceName,
    voice_speed: 1.3,
  }
}

function resolveVoiceNameByGender(gender: CharacterGender, index: 1 | 2): string {
  if (gender === 'female') return index === 1 ? EDGE_VOICE_FEMALE_1 : EDGE_VOICE_FEMALE_2
  return index === 1 ? EDGE_VOICE_MALE_1 : EDGE_VOICE_MALE_2
}

function resolveCharacterGender(characterName: string): CharacterGender {
  return CHARACTER_GENDER_MAP[characterName] || 'male'
}

function buildSinglePresetVoice(style: string): NarratorPresetVoiceProfile {
  const narratorName = SINGLE_NARRATOR_STYLE_PRESET_NAME_MAP[style] || ''
  const gender = resolveCharacterGender(narratorName)
  return buildEdgePresetVoice(resolveVoiceNameByGender(gender, 1))
}

function buildDuoPresetVoices(style: string): DuoNarratorPresetVoices {
  const names = DUO_NARRATOR_STYLE_PRESET_NAME_MAP[style]
  const role1Gender = resolveCharacterGender(names?.role_1 || '')
  const role2Gender = resolveCharacterGender(names?.role_2 || '')
  return {
    role_1: buildEdgePresetVoice(resolveVoiceNameByGender(role1Gender, 1)),
    role_2: buildEdgePresetVoice(resolveVoiceNameByGender(role2Gender, 2)),
  }
}

export const SINGLE_NARRATOR_STYLE_PRESET_VOICE_MAP: Record<string, NarratorPresetVoiceProfile> = {
  幽默: buildSinglePresetVoice('幽默'),
  犀利: buildSinglePresetVoice('犀利'),
  理性: buildSinglePresetVoice('理性'),
  讽刺: buildSinglePresetVoice('讽刺'),
  正经: buildSinglePresetVoice('正经'),
  出奇: buildSinglePresetVoice('出奇'),
  批判: buildSinglePresetVoice('批判'),
}

export const SINGLE_NARRATOR_STYLE_PRESET_APPEARANCE_MAP: Record<string, string> = {
  幽默: '四十岁左右中年男性，圆脸微肉、鼻梁略宽，浓黑短发向后梳并留细碎发，眉峰上挑，眼神机灵带笑。体型中等偏壮。上身深灰短夹克叠黑色高领内搭，下身深色直筒长裤，脚穿黑色皮靴。全身站姿放松但重心稳定，双肩微开，像见惯世面的市井能人，喜感鲜明且辨识度高。',
  犀利: '三十五岁左右硬朗男性，短寸发贴头利落，额角清爽，眉骨突出、下颌线硬，目光锋利。体型高壮、肩背宽厚。上身军绿色立领夹克配深色内搭，下身深灰工装长裤，脚穿黑色作战靴。全身站姿笔直前压，双臂自然下垂但张力明显，呈现一线指挥官的冷硬气场与强攻击性。',
  理性: '三十岁左右清瘦男性，肤色偏白，乌发高束成冠并贴服顺直，眉眼狭长，鼻梁挺直，唇线平稳。体型修长偏薄。上身月白交领长衫外搭深色披肩，腰间窄带收束，下身同色长裤，脚穿素色布靴。全身站姿端正克制，手部自然收拢，整体沉静理性，谋士气质清晰且层次分明。',
  讽刺: '四十岁左右文士男性，前额光洁、后束长辫，脸型偏长，眼尾微挑，唇角常带含笑反讽。体型中等偏瘦。上身墨蓝官服外搭黑色马褂，领口与袖缘平整挺括，下身深色长裤，脚穿黑布官靴。全身站姿从容挺直、下颌微抬，温雅外表下带机敏锋芒，士大夫神韵与讥诮感并存。',
  正经: '五十岁左右清官男性，面容清瘦、法令纹清晰，发髻规整并戴乌纱帽，眉眼沉稳不怒自威。体型偏瘦但骨架端正。上身深蓝官袍配黑色束带，衣摆垂直利落，下身同色长摆，脚穿黑色官靴。全身站姿中轴笔直、双手自然垂放，整体克己肃穆，威严与原则感非常明确。',
  出奇: '二十岁出头青年侠客，黑发高马尾配细碎刘海，眉眼清亮，鼻梁秀挺，笑意自信。体型修长精干、动作感轻快。上身靛蓝短襟侠客服叠浅色内衬，腰间系皮质束带并挂小囊，下身深色窄腿裤，脚穿轻便短靴。全身站姿微前倾、肩颈放松，少年侠气与冒险气息突出，形象明快。',
  批判: '四十岁左右现代男性，短发利落贴头，眉骨略高，面部线条硬朗，唇线紧收，目光审视感强。体型高瘦挺拔。上身深炭灰西装外套配黑色衬衫，领口干净，下身同色西裤，脚穿黑色皮鞋。全身站姿挺直克制、肩线平直，呈现高压调查者的理性锋利与不回避冲突的压迫感。',
}

export const DUO_NARRATOR_STYLE_PRESET_SETTING_MAP: Record<string, DuoNarratorPresetSettings> = {
  双讲拆解型: {
    role_1: '冷静理性，擅长先给结论再拆解逻辑与证据；表达克制清晰，像在带着听众做结构化梳理。',
    role_2: '好奇敏锐，擅长追问关键细节并把抽象概念翻译成生活化表达；语气亲切有节奏，负责推进讨论。'
  },
  辩论对抗型: {
    role_1: '立场鲜明、攻防节奏快，擅长抛出核心论点并用事实链条强压推进；说话直接有力度，重反驳与总结收束。',
    role_2: '反方视角犀利，擅长抓漏洞、追问证据边界与前提假设；语言紧凑带压迫感，强调让步条件与分歧点。'
  },
  评论解读型: {
    role_1: '负责抛出事件与关键争议点，擅长把素材讲清楚并提出“为什么值得聊”；语速明快，负责搭建讨论入口。',
    role_2: '负责背景拆解与影响评估，擅长把信息串成因果链与风险图谱；表达克制理性，强调结论可解释。'
  },
  '“主持人 + 专家”拆解型': {
    role_1: '主持人视角，擅长代表听众追问关键细节并把抽象概念翻译成生活化表达；语气亲切有节奏，负责推进讨论。',
    role_2: '专家视角，擅长先给结论再拆解逻辑与证据；表达克制清晰，输出结构化、可复述。'
  },
  '“主讲 + 捧哏”喜剧型': {
    role_1: '主讲位，包袱密度高，擅长用夸张比喻和反转句式输出观点；语气外放，节奏强，负责制造主要笑点。',
    role_2: '捧哏位，擅长接梗、抬杠与递台阶；语气机灵有反应，负责回马枪、重复梗和情绪放大，托举主讲节奏。'
  },
  '互怼吐槽型（损友感）': {
    role_1: '嘴硬爱挑刺，擅长拆台与反讽，喜欢抓对方措辞漏洞；语气冲但不失分寸，负责输出爽点与冲突张力。',
    role_2: '反击型损友，擅长顺势反打与翻旧账，快速接招不示弱；语言短促锋利，强调互怼来回与节奏感。'
  },
  '访谈挖掘型（采访感）': {
    role_1: '采访者角色，围绕目标持续追问，不跑题；擅长用递进问题逼近关键选择点，语气稳健克制。',
    role_2: '被访者/讲述者角色，擅长补足细节与转折背景；表达真诚具体，重“发生了什么、为何这么做、结果如何”。'
  },
  复盘推理型: {
    role_1: '推理主线搭建者，擅长提出假设并规划验证路径；说话结构化强，强调证据链闭环与结论可复核。',
    role_2: '证据校验者，擅长补充线索、排除干扰项与纠偏；表达谨慎务实，负责把推理从“像”拉到“成立”。'
  },
  '“共情陪伴”疗愈型': {
    role_1: '共情引导者，擅长先接住情绪再给建议；语气温柔不说教，强调具体感受被看见与被理解。',
    role_2: '现实支持者，擅长把抽象安慰落成可执行小步骤；表达平和有边界，强调可尝试、可暂停、可求助。'
  },
}

export const DUO_NARRATOR_STYLE_PRESET_NAME_MAP: Record<string, DuoNarratorPresetNames> = {
  双讲拆解型: { role_1: '包拯', role_2: '公孙策' },
  辩论对抗型: { role_1: '安欣', role_2: '高启强' },
  评论解读型: { role_1: '李达康', role_2: '沙瑞金' },
  '“主持人 + 专家”拆解型': { role_1: '唐仁', role_2: '秦风' },
  '“主讲 + 捧哏”喜剧型': { role_1: '白展堂', role_2: '郭芙蓉' },
  '互怼吐槽型（损友感）': { role_1: '燕赤霞', role_2: '宁采臣' },
  '访谈挖掘型（采访感）': { role_1: '汪淼', role_2: '叶文洁' },
  复盘推理型: { role_1: '狄仁杰', role_2: '李元芳' },
  '“共情陪伴”疗愈型': { role_1: '小龙女', role_2: '杨过' },
}

export const DUO_NARRATOR_STYLE_PRESET_APPEARANCE_MAP: Record<string, DuoNarratorPresetAppearances> = {
  双讲拆解型: {
    role_1: '四十岁左右古代官员男性，肤色偏深，方脸厚眉，鼻翼宽，目光沉稳坚硬；发冠规整并戴黑色官帽。体型中等偏壮。上身深绛官服配黑色护领与宽袖，衣摆垂坠整齐，下身深色长裤，脚穿黑色官靴。全身站姿挺直稳重、肩线平衡，秩序感与压场力强，整体气质严整不张扬。',
    role_2: '三十岁左右古代文士男性，面容清秀，眉形细长，眼神专注敏捷，发髻整齐无散发。体型修长偏瘦。上身浅青长衫叠米色内领，衣料轻薄有层次，腰间窄带收束，下身同色长裤，脚穿浅色布靴。全身站姿端正略前倾，手势克制，书卷气与信息处理敏锐感同时突出。',
  },
  辩论对抗型: {
    role_1: '三十多岁现代男性，短发平整、额头干净，颧骨略高，下颌线利落，眼神警觉而克制。体型精干结实。上身深蓝夹克配黑色内搭，下身深灰直筒长裤，脚穿深色运动靴。全身站姿紧致微前压，肩颈收束、重心稳定，整体呈现守规则但不退让的对抗气质，冷静而有韧性。',
    role_2: '四十岁左右现代男性，黑发背头整齐发亮，眉眼深、鼻梁直，嘴角带克制笑意。体型中高偏瘦。上身深灰修身西装配白衬衫，下身同色西裤，脚穿亮面黑皮鞋。全身站姿看似放松但重心前置，肩线平稳、手部收敛，显出强掌控欲和不动声色的压迫感，气场强势。',
  },
  评论解读型: {
    role_1: '四十岁左右现代男性，短发干净利落、发际线清晰，眉心轻皱，视线直给。体型中等偏瘦。上身深藏青西装配白衬衫与暗纹领带，衣装贴合，下身同色西裤，脚穿黑色商务皮鞋。全身站姿挺拔、下巴微收，状态紧绷有序，呈现高压决策者的权威感与执行力度。',
    role_2: '五十岁左右现代男性，头发后梳整齐，额角略有岁月痕迹，面部线条平稳，眼神沉静。体型中等偏壮。上身深灰商务夹克配浅色衬衣，下身深色西裤，脚穿棕黑商务皮鞋。全身站姿放松但背部挺直，双肩自然展开，整体老练审慎、稳定可信，兼具亲和与分寸感。',
  },
  '“主持人 + 专家”拆解型': {
    role_1: '三十岁左右现代男性，短卷发蓬松有层次，眉眼灵活，笑纹明显，表情外放。体型中等偏瘦。上身浅棕休闲外套配白色内搭与细项链，下身深色修身长裤，脚穿浅色休闲鞋。全身站姿轻快有弹性，身体微侧、重心灵活，舞台存在感强，亲和感与机敏感都很突出。',
    role_2: '二十多岁现代青年男性，黑色短发服帖，五官清晰，目光聚焦且冷静。体型修长偏瘦。上身深色针织上衣外搭简洁夹克，线条干净，下身深灰直筒长裤，脚穿低调深色运动鞋。全身站姿稳定克制、肩线平直，动作信息量低，整体呈现精确拆解问题的理性专家气质。',
  },
  '“主讲 + 捧哏”喜剧型': {
    role_1: '二十多岁古风男性，高束发利落，额前留短碎发，眼神机灵，笑纹明显。体型轻巧精干。上身深蓝短打并配黑色护腕与腰封，衣摆利落，下身黑色束脚长裤，脚穿软底快靴。全身站姿略侧身、肩线灵活，手部自然外展，江湖人的敏捷感与轻松戏感非常鲜明。',
    role_2: '二十多岁古风女性，高发髻紧致利落，额前短碎发贴脸，眼睛大而明亮，眉形上扬。体型纤细且有力量感。上身橙红短袄配浅色交领内衫，下身米白长裙并系窄腰封，脚穿绣纹短靴。全身站姿挺拔利落、胸背展开，神情外放直接，整体泼辣明快且极具辨识度。',
  },
  '互怼吐槽型（损友感）': {
    role_1: '三十岁左右古风侠客男性，高束发并插木簪，眉峰高、眼神锐利，面部棱角清楚。体型高大结实。上身黑色道袍叠深褐披肩与宽腰带，层次厚重，下身深色长裤，脚穿厚底黑靴。全身站姿开阔稳重、双腿分立，压迫感和硬派气质明显，形象强势但不凌乱。',
    role_2: '二十多岁古风书生男性，半束长发自然垂落，面容清秀，眼神温和却敏捷。体型偏瘦。上身浅米长衫外搭细纹轻披，领口整洁，腰间细带收束，下身同色长裤，脚穿浅棕布履。全身站姿微收但不怯、肩线略内敛，呈现温和外表下的机敏反差与书生气。',
  },
  '访谈挖掘型（采访感）': {
    role_1: '三十多岁现代理工男性，短发平整、额头开阔，五官规整，神情克制。体型中等偏瘦。上身灰蓝衬衫外搭深色功能夹克，配色低饱和，下身炭灰长裤，脚穿深色系带鞋。全身站姿中正稳健、双肩平衡，注重秩序与细节，体现严谨理性、重事实的专业气质。',
    role_2: '六十岁左右现代女性，短发贴头规整，发丝银黑相间，眼神沉静有距离感。体型偏瘦、姿态克制。上身深色素雅针织上衣外搭无图案长外套，下身深色直筒长裤，脚穿低跟皮鞋。全身站姿稳定内敛、重心平衡，神情严谨，整体高智冷静并带克制的威压感。',
  },
  复盘推理型: {
    role_1: '四十岁左右古代名臣男性，眉眼深邃，胡须修整整洁，神态凝重，官帽佩戴端正。体型中等偏壮。上身深紫官服配黑色内衬与宽袖，纹理克制，下身深色长裤，脚穿黑色官靴。全身站姿沉稳如山、目光停留有力，逻辑主导者的威严与权衡气质十分突出。',
    role_2: '三十岁左右古代护卫男性，短发束冠利落，面部干净，眼神专注警醒。体型高瘦结实。上身深青武官服配皮质护肩和护臂，腰间束带紧实，下身深色束腿裤，脚穿硬底战靴。全身站姿挺直利落、腿部支撑明确，轮廓干净，执行型武者的可靠感与纪律性很强。',
  },
  '“共情陪伴”疗愈型': {
    role_1: '二十多岁古风女性，乌黑长发垂至腰间，仅以素银发簪固定，眉眼清透柔和。体型纤细修长。上身素白轻纱交领长衣，下身同色曳地长裙，腰间细带收束，衣褶细密流畅，脚穿白色软底绣鞋。全身站姿轻柔安静、颈肩舒展，气质清冷宁定，具有温和包裹感。',
    role_2: '二十多岁古风青年男性，长发半束并留自然散发，五官温润，眼神柔和专注。体型修长匀称。上身灰青侠客服配素色内衬与窄腰带，细节简洁，下身深色长裤，脚穿灰色软皮靴。全身站姿端正沉静、肩背舒展，气质真诚可靠，传达可依靠的稳定支持感。',
  },
}

export const DUO_NARRATOR_STYLE_PRESET_VOICE_MAP: Record<string, DuoNarratorPresetVoices> = {
  双讲拆解型: buildDuoPresetVoices('双讲拆解型'),
  辩论对抗型: buildDuoPresetVoices('辩论对抗型'),
  评论解读型: buildDuoPresetVoices('评论解读型'),
  '“主持人 + 专家”拆解型': buildDuoPresetVoices('“主持人 + 专家”拆解型'),
  '“主讲 + 捧哏”喜剧型': buildDuoPresetVoices('“主讲 + 捧哏”喜剧型'),
  '互怼吐槽型（损友感）': buildDuoPresetVoices('互怼吐槽型（损友感）'),
  '访谈挖掘型（采访感）': buildDuoPresetVoices('访谈挖掘型（采访感）'),
  复盘推理型: buildDuoPresetVoices('复盘推理型'),
  '“共情陪伴”疗愈型': buildDuoPresetVoices('“共情陪伴”疗愈型'),
}

export const SINGLE_NARRATOR_STYLE_PRESET_IMAGE_ASSET_MAP: Record<string, string> = {
  幽默: '/storage/reference-library/builtin/fandebiao.png',
  犀利: '/storage/reference-library/builtin/liyunlong.png',
  理性: '/storage/reference-library/builtin/meichangsu.png',
  讽刺: '/storage/reference-library/builtin/jixiaolan.png',
  正经: '/storage/reference-library/builtin/hairui.png',
  出奇: '/storage/reference-library/builtin/lixiaoyao.png',
  批判: '/storage/reference-library/builtin/houliangping.png',
}

export const DUO_NARRATOR_STYLE_PRESET_IMAGE_ASSET_MAP: Record<string, DuoNarratorPresetImageAssets> = {
  双讲拆解型: {
    role_1: '/storage/reference-library/builtin/baozheng.png',
    role_2: '/storage/reference-library/builtin/gongsunce.png',
  },
  辩论对抗型: {
    role_1: '/storage/reference-library/builtin/anxin.png',
    role_2: '/storage/reference-library/builtin/gaoqiqiang.png',
  },
  评论解读型: {
    role_1: '/storage/reference-library/builtin/lidakang.png',
    role_2: '/storage/reference-library/builtin/sharuijin.png',
  },
  '“主持人 + 专家”拆解型': {
    role_1: '/storage/reference-library/builtin/tangren.png',
    role_2: '/storage/reference-library/builtin/qinfeng.png',
  },
  '“主讲 + 捧哏”喜剧型': {
    role_1: '/storage/reference-library/builtin/baizhantang.png',
    role_2: '/storage/reference-library/builtin/guofurong.png',
  },
  '互怼吐槽型（损友感）': {
    role_1: '/storage/reference-library/builtin/yanchixia.png',
    role_2: '/storage/reference-library/builtin/ningcaichen.png',
  },
  '访谈挖掘型（采访感）': {
    role_1: '/storage/reference-library/builtin/wangmiao.png',
    role_2: '/storage/reference-library/builtin/yewenjie.png',
  },
  复盘推理型: {
    role_1: '/storage/reference-library/builtin/direnjie.png',
    role_2: '/storage/reference-library/builtin/liyuanfang.png',
  },
  '“共情陪伴”疗愈型': {
    role_1: '/storage/reference-library/builtin/xiaolongnv.png',
    role_2: '/storage/reference-library/builtin/yangguo.png',
  },
}

export function resolveNarratorPresetSetting(style: string | undefined): string {
  const normalized = String(style || '').trim()
  if (!normalized) return ''
  return SINGLE_NARRATOR_STYLE_PRESET_SETTING_MAP[normalized] || ''
}

export function resolveNarratorPresetName(style: string | undefined): string {
  const normalized = String(style || '').trim()
  if (!normalized) return ''
  return SINGLE_NARRATOR_STYLE_PRESET_NAME_MAP[normalized] || ''
}

export function resolveNarratorCustomNameByMode(
  mode: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script',
  narratorIndex: number
): string {
  if (mode === 'single') return SINGLE_CUSTOM_NARRATOR_NAME
  if (mode === 'duo_podcast') {
    return narratorIndex === 0 ? DUO_CUSTOM_NARRATOR_NAMES[0] : DUO_CUSTOM_NARRATOR_NAMES[1]
  }
  return ''
}

export function isNarratorPresetSettingText(setting: string | undefined): boolean {
  const normalized = String(setting || '').trim()
  if (!normalized) return false
  return Object.values(SINGLE_NARRATOR_STYLE_PRESET_SETTING_MAP).includes(normalized)
}

export function isNarratorPresetNameText(name: string | undefined): boolean {
  const normalized = String(name || '').trim()
  if (!normalized) return false
  return Object.values(SINGLE_NARRATOR_STYLE_PRESET_NAME_MAP).includes(normalized)
}

export function resolveDuoNarratorPresetSettings(style: string | undefined): DuoNarratorPresetSettings | null {
  const normalized = String(style || '').trim()
  if (!normalized) return null
  return DUO_NARRATOR_STYLE_PRESET_SETTING_MAP[normalized] || null
}

export function resolveDuoNarratorPresetNames(style: string | undefined): DuoNarratorPresetNames | null {
  const normalized = String(style || '').trim()
  if (!normalized) return null
  return DUO_NARRATOR_STYLE_PRESET_NAME_MAP[normalized] || null
}

export function resolveNarratorPresetSettingByMode(
  mode: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script',
  style: string | undefined,
  narratorIndex: number
): string {
  if (mode === 'single') {
    return narratorIndex === 0 ? resolveNarratorPresetSetting(style) : ''
  }
  if (mode === 'duo_podcast') {
    const duoPreset = resolveDuoNarratorPresetSettings(style)
    if (!duoPreset) return ''
    if (narratorIndex === 0) return duoPreset.role_1
    if (narratorIndex === 1) return duoPreset.role_2
  }
  return ''
}

export function resolveNarratorPresetNameByMode(
  mode: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script',
  style: string | undefined,
  narratorIndex: number
): string {
  if (mode === 'single') {
    return narratorIndex === 0 ? resolveNarratorPresetName(style) : ''
  }
  if (mode === 'duo_podcast') {
    const duoPreset = resolveDuoNarratorPresetNames(style)
    if (!duoPreset) return ''
    if (narratorIndex === 0) return duoPreset.role_1
    if (narratorIndex === 1) return duoPreset.role_2
  }
  return ''
}

export function resolveNarratorPresetAppearanceByMode(
  mode: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script',
  style: string | undefined,
  narratorIndex: number
): string {
  const normalized = String(style || '').trim()
  if (!normalized || normalized === '__default__') return ''
  if (mode === 'single') {
    return narratorIndex === 0 ? (SINGLE_NARRATOR_STYLE_PRESET_APPEARANCE_MAP[normalized] || '') : ''
  }
  if (mode === 'duo_podcast') {
    const duoPreset = DUO_NARRATOR_STYLE_PRESET_APPEARANCE_MAP[normalized]
    if (!duoPreset) return ''
    if (narratorIndex === 0) return duoPreset.role_1
    if (narratorIndex === 1) return duoPreset.role_2
  }
  return ''
}

export function resolveNarratorPresetImageAssetByMode(
  mode: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script',
  style: string | undefined,
  narratorIndex: number
): string {
  const normalized = String(style || '').trim()
  if (!normalized || normalized === '__default__') return ''
  if (mode === 'single') {
    return narratorIndex === 0 ? (SINGLE_NARRATOR_STYLE_PRESET_IMAGE_ASSET_MAP[normalized] || '') : ''
  }
  if (mode === 'duo_podcast') {
    const duoPreset = DUO_NARRATOR_STYLE_PRESET_IMAGE_ASSET_MAP[normalized]
    if (!duoPreset) return ''
    if (narratorIndex === 0) return duoPreset.role_1
    if (narratorIndex === 1) return duoPreset.role_2
  }
  return ''
}

export function resolveNarratorPresetVoiceByMode(
  mode: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script',
  style: string | undefined,
  narratorIndex: number
): NarratorPresetVoiceProfile | null {
  const normalized = String(style || '').trim()
  if (mode === 'single' && narratorIndex === 0) {
    if (!normalized || normalized === '__default__') return SINGLE_NARRATOR_EDGE_CUSTOM_VOICE
    return SINGLE_NARRATOR_STYLE_PRESET_VOICE_MAP[normalized] || null
  }
  if (mode === 'duo_podcast') {
    if (!normalized || normalized === '__default__') {
      return narratorIndex === 0 ? DUO_NARRATOR_EDGE_CUSTOM_ROLE_1_VOICE : DUO_NARRATOR_EDGE_CUSTOM_ROLE_2_VOICE
    }
    const duoPresetVoices = DUO_NARRATOR_STYLE_PRESET_VOICE_MAP[normalized]
    if (!duoPresetVoices) return null
    if (narratorIndex === 0) return duoPresetVoices.role_1
    if (narratorIndex === 1) return duoPresetVoices.role_2
  }
  return null
}

export function isDuoNarratorPresetSettingText(setting: string | undefined): boolean {
  const normalized = String(setting || '').trim()
  if (!normalized) return false
  return Object.values(DUO_NARRATOR_STYLE_PRESET_SETTING_MAP).some(
    (preset) => preset.role_1 === normalized || preset.role_2 === normalized
  )
}

export function isDuoNarratorPresetNameText(name: string | undefined): boolean {
  const normalized = String(name || '').trim()
  if (!normalized) return false
  return Object.values(DUO_NARRATOR_STYLE_PRESET_NAME_MAP).some(
    (preset) => preset.role_1 === normalized || preset.role_2 === normalized
  )
}

export function isNarratorPresetAppearanceText(appearance: string | undefined): boolean {
  const normalized = String(appearance || '').trim()
  if (!normalized) return false
  return Object.values(SINGLE_NARRATOR_STYLE_PRESET_APPEARANCE_MAP).includes(normalized)
}

export function isDuoNarratorPresetAppearanceText(appearance: string | undefined): boolean {
  const normalized = String(appearance || '').trim()
  if (!normalized) return false
  return Object.values(DUO_NARRATOR_STYLE_PRESET_APPEARANCE_MAP).some(
    (preset) => preset.role_1 === normalized || preset.role_2 === normalized
  )
}

export function isNarratorPresetSettingTextByMode(
  mode: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script',
  setting: string | undefined
): boolean {
  if (mode === 'single') return isNarratorPresetSettingText(setting)
  if (mode === 'duo_podcast') return isDuoNarratorPresetSettingText(setting)
  return false
}

export function isNarratorPresetNameTextByMode(
  mode: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script',
  name: string | undefined
): boolean {
  if (mode === 'single') return isNarratorPresetNameText(name)
  if (mode === 'duo_podcast') {
    const normalized = String(name || '').trim()
    if (!normalized) return false
    return isDuoNarratorPresetNameText(normalized)
  }
  return false
}

export function isNarratorPresetAppearanceTextByMode(
  mode: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script',
  appearance: string | undefined
): boolean {
  if (mode === 'single') return isNarratorPresetAppearanceText(appearance)
  if (mode === 'duo_podcast') return isDuoNarratorPresetAppearanceText(appearance)
  return false
}
