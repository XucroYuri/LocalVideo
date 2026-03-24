import type { VoiceInfo, Wan2gpAudioPreset } from '@/types/settings'

export type ReferenceVoiceProvider =
  | 'edge_tts'
  | 'wan2gp'
  | 'volcengine_tts'
  | 'kling_tts'
  | 'vidu_tts'
  | 'minimax_tts'
  | 'xiaomi_mimo_tts'

export interface VoiceOption {
  value: string
  label: string
}

export interface XiaomiMimoTtsVoiceVariant extends VoiceOption {
  voice: string
  stylePreset: string
}

export interface KlingTtsVoiceOption {
  name: string
  voiceId: string
  language: 'zh' | 'en'
}

export const EDGE_TTS_DEFAULT_VOICE = 'zh-CN-YunjianNeural'
export const EDGE_TTS_DUO_ROLE_1_VOICE = 'zh-CN-YunjianNeural'
export const EDGE_TTS_DUO_ROLE_2_VOICE = 'zh-CN-XiaoyiNeural'
export const VOLCENGINE_TTS_DEFAULT_VOICE = 'zh_female_vv_uranus_bigtts'
export const WAN2GP_DEFAULT_MODE = 'serena'
export const KLING_TTS_DEFAULT_VOICE = 'genshin_vindi2'
export const VIDU_TTS_DEFAULT_VOICE = 'female-shaonv'
export const MINIMAX_TTS_DEFAULT_VOICE = 'Chinese (Mandarin)_Reliable_Executive'
export const XIAOMI_MIMO_TTS_DEFAULT_VOICE = 'mimo_default'

export const EDGE_TTS_FALLBACK_OPTIONS: VoiceOption[] = [
  { value: 'zh-CN-YunjianNeural', label: '云健（男声）' },
  { value: 'zh-CN-YunxiNeural', label: '云希（男声）' },
  { value: 'zh-CN-XiaoxiaoNeural', label: '晓晓（女声）' },
  { value: 'zh-CN-XiaoyiNeural', label: '晓伊（女声）' },
]

export const WAN2GP_FALLBACK_MODE_OPTIONS: VoiceOption[] = [
  { value: 'serena', label: 'Serena' },
  { value: 'aiden', label: 'Aiden' },
  { value: 'dylan', label: 'Dylan' },
  { value: 'eric', label: 'Eric' },
  { value: 'ono_anna', label: 'Ono Anna' },
  { value: 'ryan', label: 'Ryan' },
  { value: 'v_serena', label: 'V Serena' },
  { value: 'sohee', label: 'Sohee' },
  { value: 'uncle_fu', label: 'Uncle Fu' },
  { value: 'vivian', label: 'Vivian' },
]

export const VOLCENGINE_TTS_FALLBACK_OPTIONS: VoiceOption[] = [
  { value: 'zh_female_vv_uranus_bigtts', label: 'Vivi 2.0' },
  { value: 'zh_female_wanqudashu_moon_bigtts', label: '湾区大叔（zh_female_wanqudashu_moon_bigtts）' },
  { value: 'zh_female_daimengchuanmei_moon_bigtts', label: '呆萌川妹（zh_female_daimengchuanmei_moon_bigtts）' },
  { value: 'zh_male_guozhoudege_moon_bigtts', label: '广州德哥（zh_male_guozhoudege_moon_bigtts）' },
  { value: 'zh_male_beijingxiaoye_moon_bigtts', label: '北京小爷（zh_male_beijingxiaoye_moon_bigtts）' },
  { value: 'zh_male_shaonianzixin_moon_bigtts', label: '少年梓辛（zh_male_shaonianzixin_moon_bigtts）' },
  { value: 'zh_female_meilinvyou_moon_bigtts', label: '魅力女友（zh_female_meilinvyou_moon_bigtts）' },
  { value: 'zh_male_shenyeboke_moon_bigtts', label: '深夜播客（zh_male_shenyeboke_moon_bigtts）' },
  { value: 'zh_male_haoyuxiaoge_moon_bigtts', label: '浩宇小哥（zh_male_haoyuxiaoge_moon_bigtts）' },
  { value: 'zh_female_cancan_mars_bigtts', label: '灿灿（zh_female_cancan_mars_bigtts）' },
  { value: 'zh_female_qingxinnvsheng_mars_bigtts', label: '清新女声（zh_female_qingxinnvsheng_mars_bigtts）' },
  { value: 'zh_male_qingshuangnanda_mars_bigtts', label: '清爽男大（zh_male_qingshuangnanda_mars_bigtts）' },
  { value: 'zh_male_yangguangqingnian_mars_bigtts', label: '阳光青年（zh_male_yangguangqingnian_mars_bigtts）' },
]
export const KLING_TTS_VOICE_CATALOG: KlingTtsVoiceOption[] = [
  { name: '阳光少年', voiceId: 'genshin_vindi2', language: 'zh' },
  { name: '懂事小弟', voiceId: 'zhinen_xuesheng', language: 'zh' },
  { name: '运动少年', voiceId: 'tiyuxi_xuedi', language: 'zh' },
  { name: '青春少女', voiceId: 'ai_shatang', language: 'zh' },
  { name: '温柔小妹', voiceId: 'genshin_klee2', language: 'zh' },
  { name: '元气少女', voiceId: 'genshin_kirara', language: 'zh' },
  { name: '阳光男生', voiceId: 'ai_kaiya', language: 'zh' },
  { name: '幽默小哥', voiceId: 'tiexin_nanyou', language: 'zh' },
  { name: '文艺小哥', voiceId: 'ai_chenjiahao_712', language: 'zh' },
  { name: '甜美邻家', voiceId: 'girlfriend_1_speech02', language: 'zh' },
  { name: '温柔姐姐', voiceId: 'chat1_female_new-3', language: 'zh' },
  { name: '职场女青', voiceId: 'girlfriend_2_speech02', language: 'zh' },
  { name: '活泼男童', voiceId: 'cartoon-boy-07', language: 'zh' },
  { name: '俏皮女童', voiceId: 'cartoon-girl-01', language: 'zh' },
  { name: '稳重老爸', voiceId: 'ai_huangyaoshi_712', language: 'zh' },
  { name: '温柔妈妈', voiceId: 'you_pingjing', language: 'zh' },
  { name: '严肃上司', voiceId: 'ai_laoguowang_712', language: 'zh' },
  { name: '优雅贵妇', voiceId: 'chengshu_jiejie', language: 'zh' },
  { name: '慈祥爷爷', voiceId: 'zhuxi_speech02', language: 'zh' },
  { name: '唠叨爷爷', voiceId: 'uk_oldman3', language: 'zh' },
  { name: '唠叨奶奶', voiceId: 'laopopo_speech02', language: 'zh' },
  { name: '和蔼奶奶', voiceId: 'heainainai_speech02', language: 'zh' },
  { name: '东北老铁', voiceId: 'dongbeilaotie_speech02', language: 'zh' },
  { name: '重庆小伙', voiceId: 'chongqingxiaohuo_speech02', language: 'zh' },
  { name: '四川妹子', voiceId: 'chuanmeizi_speech02', language: 'zh' },
  { name: '潮汕大叔', voiceId: 'chaoshandashu_speech02', language: 'zh' },
  { name: '台湾男生', voiceId: 'ai_taiwan_man2_speech02', language: 'zh' },
  { name: '西安掌柜', voiceId: 'xianzhanggui_speech02', language: 'zh' },
  { name: '天津姐姐', voiceId: 'tianjinjiejie_speech02', language: 'zh' },
  { name: '新闻播报男', voiceId: 'diyinnansang_DB_CN_M_04-v2', language: 'zh' },
  { name: '译制片男', voiceId: 'yizhipiannan-v1', language: 'zh' },
  { name: '元气少女', voiceId: 'guanxiaofang-v2', language: 'zh' },
  { name: '撒娇女友', voiceId: 'tianmeixuemei-v1', language: 'zh' },
  { name: '刀片烟嗓', voiceId: 'daopianyansang-v1', language: 'zh' },
  { name: '乖巧正太', voiceId: 'mengwa-v1', language: 'zh' },
  { name: 'Sunny', voiceId: 'genshin_vindi2', language: 'en' },
  { name: 'Sage', voiceId: 'zhinen_xuesheng', language: 'en' },
  { name: 'Ace', voiceId: 'AOT', language: 'en' },
  { name: 'Blossom', voiceId: 'ai_shatang', language: 'en' },
  { name: 'Peppy', voiceId: 'genshin_klee2', language: 'en' },
  { name: 'Dove', voiceId: 'genshin_kirara', language: 'en' },
  { name: 'Shine', voiceId: 'ai_kaiya', language: 'en' },
  { name: 'Anchor', voiceId: 'oversea_male1', language: 'en' },
  { name: 'Lyric', voiceId: 'ai_chenjiahao_712', language: 'en' },
  { name: 'Melody', voiceId: 'girlfriend_4_speech02', language: 'en' },
  { name: 'Tender', voiceId: 'chat1_female_new-3', language: 'en' },
  { name: 'Siren', voiceId: 'chat_0407_5-1', language: 'en' },
  { name: 'Zippy', voiceId: 'cartoon-boy-07', language: 'en' },
  { name: 'Bud', voiceId: 'uk_boy1', language: 'en' },
  { name: 'Sprite', voiceId: 'cartoon-girl-01', language: 'en' },
  { name: 'Candy', voiceId: 'PeppaPig_platform', language: 'en' },
  { name: 'Beacon', voiceId: 'ai_huangzhong_712', language: 'en' },
  { name: 'Rock', voiceId: 'ai_huangyaoshi_712', language: 'en' },
  { name: 'Titan', voiceId: 'ai_laoguowang_712', language: 'en' },
  { name: 'Grace', voiceId: 'chengshu_jiejie', language: 'en' },
  { name: 'Helen', voiceId: 'you_pingjing', language: 'en' },
  { name: 'Lore', voiceId: 'calm_story1', language: 'en' },
  { name: 'Crag', voiceId: 'uk_man2', language: 'en' },
  { name: 'Prattle', voiceId: 'laopopo_speech02', language: 'en' },
  { name: 'Hearth', voiceId: 'heainainai_speech02', language: 'en' },
  { name: 'The Reader', voiceId: 'reader_en_m-v1', language: 'en' },
  { name: 'Commercial Lady', voiceId: 'commercial_lady_en_f-v1', language: 'en' },
]
export function toKlingVoiceOptionValue(voiceId: string, language: 'zh' | 'en'): string {
  return `${voiceId}::${language}`
}
export const KLING_TTS_FALLBACK_OPTIONS: VoiceOption[] = KLING_TTS_VOICE_CATALOG.filter(
  (item, index, array) => array.findIndex((candidate) => candidate.voiceId === item.voiceId) === index
).map((item) => ({
  value: item.voiceId,
  label: item.name,
}))
export const VIDU_TTS_FALLBACK_OPTIONS: VoiceOption[] = [
  { value: 'male-qn-qingse', label: '青涩青年音色' },
  { value: 'male-qn-jingying', label: '精英青年音色' },
  { value: 'male-qn-badao', label: '霸道青年音色' },
  { value: 'male-qn-daxuesheng', label: '青年大学生音色' },
  { value: 'female-shaonv', label: '少女音色' },
  { value: 'female-yujie', label: '御姐音色' },
  { value: 'female-chengshu', label: '成熟女性音色' },
  { value: 'female-tianmei', label: '甜美女性音色' },
  { value: 'male-qn-qingse-jingpin', label: '青涩青年音色-beta' },
  { value: 'male-qn-jingying-jingpin', label: '精英青年音色-beta' },
  { value: 'male-qn-badao-jingpin', label: '霸道青年音色-beta' },
  { value: 'male-qn-daxuesheng-jingpin', label: '青年大学生音色-beta' },
  { value: 'female-shaonv-jingpin', label: '少女音色-beta' },
  { value: 'female-yujie-jingpin', label: '御姐音色-beta' },
  { value: 'female-chengshu-jingpin', label: '成熟女性音色-beta' },
  { value: 'female-tianmei-jingpin', label: '甜美女性音色-beta' },
  { value: 'clever_boy', label: '聪明男童' },
  { value: 'cute_boy', label: '可爱男童' },
  { value: 'lovely_girl', label: '萌萌女童' },
  { value: 'cartoon_pig', label: '卡通猪小琪' },
  { value: 'bingjiao_didi', label: '病娇弟弟' },
  { value: 'junlang_nanyou', label: '俊朗男友' },
  { value: 'chunzhen_xuedi', label: '纯真学弟' },
  { value: 'lengdan_xiongzhang', label: '冷淡学长' },
  { value: 'badao_shaoye', label: '霸道少爷' },
  { value: 'tianxin_xiaoling', label: '甜心小玲' },
  { value: 'qiaopi_mengmei', label: '俏皮萌妹' },
  { value: 'wumei_yujie', label: '妩媚御姐' },
  { value: 'diadia_xuemei', label: '嗲嗲学妹' },
  { value: 'danya_xuejie', label: '淡雅学姐' },
  { value: 'Chinese (Mandarin)_Reliable_Executive', label: '沉稳高管' },
  { value: 'Chinese (Mandarin)_News_Anchor', label: '新闻女声' },
  { value: 'Chinese (Mandarin)_Mature_Woman', label: '傲娇御姐' },
  { value: 'Chinese (Mandarin)_Unrestrained_Young_Man', label: '不羁青年' },
  { value: 'Arrogant_Miss', label: '嚣张小姐' },
  { value: 'Robot_Armor', label: '机械战甲' },
  { value: 'Chinese (Mandarin)_Kind-hearted_Antie', label: '热心大婶' },
  { value: 'Chinese (Mandarin)_HK_Flight_Attendant', label: '港普空姐' },
  { value: 'Chinese (Mandarin)_Humorous_Elder', label: '搞笑大爷' },
  { value: 'Chinese (Mandarin)_Gentleman', label: '温润男声' },
  { value: 'Chinese (Mandarin)_Warm_Bestie', label: '温暖闺蜜' },
  { value: 'Chinese (Mandarin)_Male_Announcer', label: '播报男声' },
  { value: 'Chinese (Mandarin)_Sweet_Lady', label: '甜美女声' },
  { value: 'Chinese (Mandarin)_Southern_Young_Man', label: '南方小哥' },
  { value: 'Chinese (Mandarin)_Wise_Women', label: '阅历姐姐' },
  { value: 'Chinese (Mandarin)_Gentle_Youth', label: '温润青年' },
  { value: 'Chinese (Mandarin)_Warm_Girl', label: '温暖少女' },
  { value: 'Chinese (Mandarin)_Kind-hearted_Elder', label: '花甲奶奶' },
  { value: 'Chinese (Mandarin)_Cute_Spirit', label: '憨憨萌兽' },
  { value: 'Chinese (Mandarin)_Radio_Host', label: '电台男主播' },
  { value: 'Chinese (Mandarin)_Lyrical_Voice', label: '抒情男声' },
  { value: 'Chinese (Mandarin)_Straightforward_Boy', label: '率真弟弟' },
  { value: 'Chinese (Mandarin)_Sincere_Adult', label: '真诚青年' },
  { value: 'Chinese (Mandarin)_Gentle_Senior', label: '温柔学姐' },
  { value: 'Chinese (Mandarin)_Stubborn_Friend', label: '嘴硬竹马' },
  { value: 'Chinese (Mandarin)_Crisp_Girl', label: '清脆少女' },
  { value: 'Chinese (Mandarin)_Pure-hearted_Boy', label: '清澈邻家弟弟' },
  { value: 'Chinese (Mandarin)_Soft_Girl', label: '软软女孩' },
  { value: 'Cantonese_ProfessionalHost（F)', label: '专业女主持（粤语）' },
  { value: 'Cantonese_GentleLady', label: '温柔女声（粤语）' },
  { value: 'Cantonese_ProfessionalHost（M)', label: '专业男主持（粤语）' },
  { value: 'Cantonese_PlayfulMan', label: '活泼男声（粤语）' },
  { value: 'Cantonese_CuteGirl', label: '可爱女孩（粤语）' },
  { value: 'Cantonese_KindWoman', label: '善良女声（粤语）' },
]
export const XIAOMI_MIMO_TTS_FALLBACK_OPTIONS: VoiceOption[] = [
  { value: 'mimo_default', label: 'MiMo 默认' },
  { value: 'default_zh', label: 'MiMo 中文女声' },
  { value: 'default_en', label: 'MiMo 英文女声' },
]
export const XIAOMI_MIMO_TTS_STYLE_PRESET_OPTIONS: VoiceOption[] = [
  { value: 'sun_wukong', label: '孙悟空' },
  { value: 'lin_dai_yu', label: '林黛玉' },
  { value: 'jia_zi_yin', label: '夹子音' },
  { value: 'tai_wan_qiang', label: '台湾腔' },
  { value: 'dong_bei_lao_tie', label: '东北话' },
  { value: 'yue_yu_zhu_bo', label: '粤语' },
  { value: 'ao_jiao_yu_jie', label: '傲娇御姐' },
  { value: 'wen_rou_xue_jie', label: '温柔学姐' },
  { value: 'bing_jiao_di_di', label: '病娇弟弟' },
  { value: 'ba_dao_shao_ye', label: '霸道少爷' },
  { value: 'sa_jiao_nv_you', label: '撒娇女友' },
  { value: 'gang_pu_kong_jie', label: '港普空姐' },
  { value: 'bo_bao_nan_sheng', label: '播报男声' },
  { value: 'ruan_ruan_nv_hai', label: '软软女孩' },
  { value: 'wen_nuan_shao_nv', label: '温暖少女' },
]
export const XIAOMI_MIMO_TTS_COMBINED_VOICE_OPTIONS: XiaomiMimoTtsVoiceVariant[] = [
  {
    value: 'voice::mimo_default',
    label: 'MiMo 默认',
    voice: 'mimo_default',
    stylePreset: '',
  },
  {
    value: 'voice::default_zh',
    label: 'MiMo 中文女声',
    voice: 'default_zh',
    stylePreset: '',
  },
  {
    value: 'voice::default_en',
    label: 'MiMo 英文女声',
    voice: 'default_en',
    stylePreset: '',
  },
  {
    value: 'style::sun_wukong',
    label: '孙悟空',
    voice: 'mimo_default',
    stylePreset: 'sun_wukong',
  },
  {
    value: 'style::lin_dai_yu',
    label: '林黛玉',
    voice: 'mimo_default',
    stylePreset: 'lin_dai_yu',
  },
  {
    value: 'style::jia_zi_yin',
    label: '夹子音',
    voice: 'mimo_default',
    stylePreset: 'jia_zi_yin',
  },
  {
    value: 'style::tai_wan_qiang',
    label: '台湾腔',
    voice: 'mimo_default',
    stylePreset: 'tai_wan_qiang',
  },
  {
    value: 'style::dong_bei_lao_tie',
    label: '东北话',
    voice: 'mimo_default',
    stylePreset: 'dong_bei_lao_tie',
  },
  {
    value: 'style::yue_yu_zhu_bo',
    label: '粤语',
    voice: 'mimo_default',
    stylePreset: 'yue_yu_zhu_bo',
  },
  {
    value: 'style::ao_jiao_yu_jie',
    label: '傲娇御姐',
    voice: 'mimo_default',
    stylePreset: 'ao_jiao_yu_jie',
  },
  {
    value: 'style::wen_rou_xue_jie',
    label: '温柔学姐',
    voice: 'mimo_default',
    stylePreset: 'wen_rou_xue_jie',
  },
  {
    value: 'style::bing_jiao_di_di',
    label: '病娇弟弟',
    voice: 'mimo_default',
    stylePreset: 'bing_jiao_di_di',
  },
  {
    value: 'style::ba_dao_shao_ye',
    label: '霸道少爷',
    voice: 'mimo_default',
    stylePreset: 'ba_dao_shao_ye',
  },
  {
    value: 'style::sa_jiao_nv_you',
    label: '撒娇女友',
    voice: 'mimo_default',
    stylePreset: 'sa_jiao_nv_you',
  },
  {
    value: 'style::gang_pu_kong_jie',
    label: '港普空姐',
    voice: 'mimo_default',
    stylePreset: 'gang_pu_kong_jie',
  },
  {
    value: 'style::bo_bao_nan_sheng',
    label: '播报男声',
    voice: 'mimo_default',
    stylePreset: 'bo_bao_nan_sheng',
  },
  {
    value: 'style::ruan_ruan_nv_hai',
    label: '软软女孩',
    voice: 'mimo_default',
    stylePreset: 'ruan_ruan_nv_hai',
  },
  {
    value: 'style::wen_nuan_shao_nv',
    label: '温暖少女',
    voice: 'mimo_default',
    stylePreset: 'wen_nuan_shao_nv',
  },
]
export const MINIMAX_TTS_FALLBACK_OPTIONS: VoiceOption[] = [
  { value: 'male-qn-qingse', label: '青涩青年音色' },
  { value: 'male-qn-jingying', label: '精英青年音色' },
  { value: 'male-qn-badao', label: '霸道青年音色' },
  { value: 'male-qn-daxuesheng', label: '青年大学生音色' },
  { value: 'female-shaonv', label: '少女音色' },
  { value: 'female-yujie', label: '御姐音色' },
  { value: 'female-chengshu', label: '成熟女性音色' },
  { value: 'female-tianmei', label: '甜美女性音色' },
  { value: 'male-qn-qingse-jingpin', label: '青涩青年音色-beta' },
  { value: 'male-qn-jingying-jingpin', label: '精英青年音色-beta' },
  { value: 'male-qn-badao-jingpin', label: '霸道青年音色-beta' },
  { value: 'male-qn-daxuesheng-jingpin', label: '青年大学生音色-beta' },
  { value: 'female-shaonv-jingpin', label: '少女音色-beta' },
  { value: 'female-yujie-jingpin', label: '御姐音色-beta' },
  { value: 'female-chengshu-jingpin', label: '成熟女性音色-beta' },
  { value: 'female-tianmei-jingpin', label: '甜美女性音色-beta' },
  { value: 'clever_boy', label: '聪明男童' },
  { value: 'cute_boy', label: '可爱男童' },
  { value: 'lovely_girl', label: '萌萌女童' },
  { value: 'cartoon_pig', label: '卡通猪小琪' },
  { value: 'bingjiao_didi', label: '病娇弟弟' },
  { value: 'junlang_nanyou', label: '俊朗男友' },
  { value: 'chunzhen_xuedi', label: '纯真学弟' },
  { value: 'lengdan_xiongzhang', label: '冷淡学长' },
  { value: 'badao_shaoye', label: '霸道少爷' },
  { value: 'tianxin_xiaoling', label: '甜心小玲' },
  { value: 'qiaopi_mengmei', label: '俏皮萌妹' },
  { value: 'wumei_yujie', label: '妩媚御姐' },
  { value: 'diadia_xuemei', label: '嗲嗲学妹' },
  { value: 'danya_xuejie', label: '淡雅学姐' },
  { value: 'Chinese (Mandarin)_Reliable_Executive', label: '沉稳高管' },
  { value: 'Chinese (Mandarin)_News_Anchor', label: '新闻女声' },
  { value: 'Chinese (Mandarin)_Mature_Woman', label: '傲娇御姐' },
  { value: 'Chinese (Mandarin)_Unrestrained_Young_Man', label: '不羁青年' },
  { value: 'Arrogant_Miss', label: '嚣张小姐' },
  { value: 'Robot_Armor', label: '机械战甲' },
  { value: 'Chinese (Mandarin)_Kind-hearted_Antie', label: '热心大婶' },
  { value: 'Chinese (Mandarin)_HK_Flight_Attendant', label: '港普空姐' },
  { value: 'Chinese (Mandarin)_Humorous_Elder', label: '搞笑大爷' },
  { value: 'Chinese (Mandarin)_Gentleman', label: '温润男声' },
  { value: 'Chinese (Mandarin)_Warm_Bestie', label: '温暖闺蜜' },
  { value: 'Chinese (Mandarin)_Male_Announcer', label: '播报男声' },
  { value: 'Chinese (Mandarin)_Sweet_Lady', label: '甜美女声' },
  { value: 'Chinese (Mandarin)_Southern_Young_Man', label: '南方小哥' },
  { value: 'Chinese (Mandarin)_Wise_Women', label: '阅历姐姐' },
  { value: 'Chinese (Mandarin)_Gentle_Youth', label: '温润青年' },
  { value: 'Chinese (Mandarin)_Warm_Girl', label: '温暖少女' },
  { value: 'Chinese (Mandarin)_Kind-hearted_Elder', label: '花甲奶奶' },
  { value: 'Chinese (Mandarin)_Cute_Spirit', label: '憨憨萌兽' },
  { value: 'Chinese (Mandarin)_Radio_Host', label: '电台男主播' },
  { value: 'Chinese (Mandarin)_Lyrical_Voice', label: '抒情男声' },
  { value: 'Chinese (Mandarin)_Straightforward_Boy', label: '率真弟弟' },
  { value: 'Chinese (Mandarin)_Sincere_Adult', label: '真诚青年' },
  { value: 'Chinese (Mandarin)_Gentle_Senior', label: '温柔学姐' },
  { value: 'Chinese (Mandarin)_Stubborn_Friend', label: '嘴硬竹马' },
  { value: 'Chinese (Mandarin)_Crisp_Girl', label: '清脆少女' },
  { value: 'Chinese (Mandarin)_Pure-hearted_Boy', label: '清澈邻家弟弟' },
  { value: 'Chinese (Mandarin)_Soft_Girl', label: '软软女孩' },
  { value: 'Cantonese_ProfessionalHost（F)', label: '专业女主持' },
  { value: 'Cantonese_GentleLady', label: '温柔女声' },
  { value: 'Cantonese_ProfessionalHost（M)', label: '专业男主持' },
  { value: 'Cantonese_PlayfulMan', label: '活泼男声' },
  { value: 'Cantonese_CuteGirl', label: '可爱女孩' },
  { value: 'Cantonese_KindWoman', label: '善良女声' },
]

export function toFiniteNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return undefined
}

export function toFiniteInt(value: unknown): number | undefined {
  const num = toFiniteNumber(value)
  if (num === undefined) return undefined
  return Math.trunc(num)
}

export function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

export function normalizeVoiceProvider(value: unknown): ReferenceVoiceProvider {
  const normalized = String(value || '').trim().toLowerCase()
  if (normalized === 'wan2gp') return 'wan2gp'
  if (normalized === 'volcengine_tts') return 'volcengine_tts'
  if (normalized === 'kling_tts') return 'kling_tts'
  if (normalized === 'vidu_tts') return 'vidu_tts'
  if (normalized === 'minimax_tts') return 'minimax_tts'
  if (normalized === 'xiaomi_mimo_tts') return 'xiaomi_mimo_tts'
  return 'edge_tts'
}

export function getReferenceVoiceProviderLabel(provider: ReferenceVoiceProvider | string | undefined): string {
  const normalized = normalizeVoiceProvider(provider)
  if (normalized === 'wan2gp') return 'Wan2GP'
  if (normalized === 'volcengine_tts') return '火山引擎 TTS'
  if (normalized === 'kling_tts') return '可灵TTS'
  if (normalized === 'vidu_tts') return 'Vidu TTS'
  if (normalized === 'minimax_tts') return 'MiniMax TTS'
  if (normalized === 'xiaomi_mimo_tts') return '小米 MiMo TTS'
  return 'Edge TTS'
}

export function rateToSpeed(rate: string): number {
  const match = String(rate || '').match(/([+-]?\d+)%/)
  if (!match) return 1.0
  return 1 + parseInt(match[1], 10) / 100
}

export function speedToRate(speed: number): string {
  const percent = Math.round((speed - 1) * 100)
  return percent >= 0 ? `+${percent}%` : `${percent}%`
}

export function resolveAvailableAudioProviders(
  providerCandidates: unknown[] | undefined,
  wan2gpAvailable: boolean | undefined
): ReferenceVoiceProvider[] {
  const providers = (providerCandidates || [])
    .map((item) => String(item || '').trim())
    .filter((item): item is ReferenceVoiceProvider => (
      item === 'edge_tts'
      || item === 'wan2gp'
      || item === 'volcengine_tts'
      || item === 'kling_tts'
      || item === 'vidu_tts'
      || item === 'minimax_tts'
      || item === 'xiaomi_mimo_tts'
    ))
  if (providers.length > 0) return providers
  return wan2gpAvailable ? ['edge_tts', 'wan2gp'] : ['edge_tts']
}

export function resolveDefaultAudioProvider(
  configuredProvider: unknown,
  availableAudioProviders: ReferenceVoiceProvider[]
): ReferenceVoiceProvider {
  const configured = String(configuredProvider || '').trim()
  if (
    (
      configured === 'edge_tts'
      || configured === 'wan2gp'
      || configured === 'volcengine_tts'
      || configured === 'kling_tts'
      || configured === 'vidu_tts'
      || configured === 'minimax_tts'
      || configured === 'xiaomi_mimo_tts'
    )
    && availableAudioProviders.includes(configured)
  ) {
    return configured
  }
  return availableAudioProviders[0] || 'edge_tts'
}

export function mapEdgeVoiceOptions(voices: VoiceInfo[] | undefined): VoiceOption[] {
  const fetched = (voices || [])
    .map((voice) => ({
      value: String(voice.id || '').trim(),
      label: String(voice.name || '').trim() || String(voice.id || '').trim(),
    }))
    .filter((item) => !!item.value)
  return fetched.length > 0 ? fetched : EDGE_TTS_FALLBACK_OPTIONS
}

export function mapVolcengineVoiceOptions(voices: VoiceInfo[] | undefined): VoiceOption[] {
  const fetched = (voices || [])
    .map((voice) => ({
      value: String(voice.id || '').trim(),
      label: String(voice.name || '').trim() || String(voice.id || '').trim(),
    }))
    .filter((item) => !!item.value)
  return fetched.length > 0 ? fetched : VOLCENGINE_TTS_FALLBACK_OPTIONS
}

export function resolveDefaultWan2gpPresetId(
  configuredPreset: unknown,
  presets: Wan2gpAudioPreset[]
): string {
  const configuredId = String(configuredPreset || '').trim()
  const preferredPresetId = presets.find((item) => item.id === configuredId)?.id
  if (preferredPresetId) return preferredPresetId
  return (
    presets.find((item) => item.id === 'qwen3_tts_base')?.id
    || presets[0]?.id
    || 'qwen3_tts_base'
  )
}

export function resolveWan2gpPreset(
  presets: Wan2gpAudioPreset[],
  defaultPresetId: string,
  presetId?: string
): Wan2gpAudioPreset | undefined {
  const targetId = String(presetId || '').trim()
  if (targetId) {
    const matched = presets.find((item) => item.id === targetId)
    if (matched) return matched
  }
  return presets.find((item) => item.id === defaultPresetId) || presets[0]
}

export function mapWan2gpModeOptions(preset: Wan2gpAudioPreset | undefined): VoiceOption[] {
  const mapped = (preset?.model_mode_choices || [])
    .map((choice) => ({
      value: String(choice.id || '').trim(),
      label: String(choice.label || '').trim() || String(choice.id || '').trim(),
    }))
    .filter((item) => !!item.value)
  return mapped.length > 0 ? mapped : WAN2GP_FALLBACK_MODE_OPTIONS
}

export function resolveVoiceOptions(params: {
  provider: ReferenceVoiceProvider
  edgeVoiceOptions: VoiceOption[]
  volcengineVoiceOptions: VoiceOption[]
  wan2gpPresets: Wan2gpAudioPreset[]
  defaultWan2gpPresetId: string
  presetId?: string
}): VoiceOption[] {
  const {
    provider,
    edgeVoiceOptions,
    volcengineVoiceOptions,
    wan2gpPresets,
    defaultWan2gpPresetId,
    presetId,
  } = params
  if (provider === 'edge_tts') return edgeVoiceOptions
  if (provider === 'volcengine_tts') return volcengineVoiceOptions
  if (provider === 'kling_tts') return KLING_TTS_FALLBACK_OPTIONS
  if (provider === 'vidu_tts') return VIDU_TTS_FALLBACK_OPTIONS
  if (provider === 'minimax_tts') return MINIMAX_TTS_FALLBACK_OPTIONS
  if (provider === 'xiaomi_mimo_tts') return XIAOMI_MIMO_TTS_FALLBACK_OPTIONS
  const preset = resolveWan2gpPreset(wan2gpPresets, defaultWan2gpPresetId, presetId)
  return mapWan2gpModeOptions(preset)
}

export function resolveVoiceLabel(params: {
  provider: ReferenceVoiceProvider
  voiceName: string | undefined
  edgeVoiceOptions: VoiceOption[]
  volcengineVoiceOptions: VoiceOption[]
  wan2gpPresets: Wan2gpAudioPreset[]
  defaultWan2gpPresetId: string
  presetId?: string
}): string {
  const normalizedVoiceName = String(params.voiceName || '').trim()
  if (!normalizedVoiceName) return '未设置'
  const source = resolveVoiceOptions({
    provider: params.provider,
    edgeVoiceOptions: params.edgeVoiceOptions,
    volcengineVoiceOptions: params.volcengineVoiceOptions,
    wan2gpPresets: params.wan2gpPresets,
    defaultWan2gpPresetId: params.defaultWan2gpPresetId,
    presetId: params.presetId,
  })
  return source.find((item) => item.value === normalizedVoiceName)?.label || normalizedVoiceName
}
