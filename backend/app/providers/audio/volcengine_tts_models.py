from __future__ import annotations

from typing import Any

VOLCENGINE_TTS_MODEL_SEED_1_0 = "seed-tts-1.0"
VOLCENGINE_TTS_MODEL_SEED_2_0 = "seed-tts-2.0"
VOLCENGINE_TTS_DEFAULT_MODEL_NAME = VOLCENGINE_TTS_MODEL_SEED_2_0
# V3 HTTP 单向流接口下，按模型映射 resource_id。
VOLCENGINE_TTS_DEFAULT_RESOURCE_ID = "seed-tts-2.0"
VOLCENGINE_TTS_DEFAULT_VOICE_TYPE = "zh_female_vv_uranus_bigtts"

VOLCENGINE_TTS_MODEL_RESOURCE_MAP: dict[str, str] = {
    VOLCENGINE_TTS_MODEL_SEED_1_0: "seed-tts-1.0",
    VOLCENGINE_TTS_MODEL_SEED_2_0: "seed-tts-2.0",
}

VOLCENGINE_TTS_MODEL_VOICE_MAP: dict[str, tuple[dict[str, str], ...]] = {
    VOLCENGINE_TTS_MODEL_SEED_1_0: (
        {
            "id": "zh_male_lengkugege_emo_v2_mars_bigtts",
            "name": "冷酷哥哥",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_tianxinxiaomei_emo_v2_mars_bigtts",
            "name": "甜心小美",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_gaolengyujie_emo_v2_mars_bigtts",
            "name": "高冷御姐",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_aojiaobazong_emo_v2_mars_bigtts",
            "name": "傲娇霸总",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_guangzhoudege_emo_mars_bigtts",
            "name": "广州德哥",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_jingqiangkanye_emo_mars_bigtts",
            "name": "京腔侃爷",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_linjuayi_emo_v2_mars_bigtts",
            "name": "邻居阿姨",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_yourougongzi_emo_v2_mars_bigtts",
            "name": "优柔公子",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_ruyayichen_emo_v2_mars_bigtts",
            "name": "儒雅男友",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_junlangnanyou_emo_v2_mars_bigtts",
            "name": "俊朗男友",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_beijingxiaoye_emo_v2_mars_bigtts",
            "name": "北京小爷",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_roumeinvyou_emo_v2_mars_bigtts",
            "name": "柔美女友",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_yangguangqingnian_emo_v2_mars_bigtts",
            "name": "阳光青年",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_meilinvyou_emo_v2_mars_bigtts",
            "name": "魅力女友",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_shuangkuaisisi_emo_v2_mars_bigtts",
            "name": "爽快思思",
            "locale": "zh-CN/en-GB",
        },
        {
            "id": "en_female_candice_emo_v2_mars_bigtts",
            "name": "Candice",
            "locale": "en-US",
        },
        {
            "id": "en_female_skye_emo_v2_mars_bigtts",
            "name": "Serena",
            "locale": "en-US",
        },
        {
            "id": "en_male_glen_emo_v2_mars_bigtts",
            "name": "Glen",
            "locale": "en-US",
        },
        {
            "id": "en_male_sylus_emo_v2_mars_bigtts",
            "name": "Sylus",
            "locale": "en-US",
        },
        {
            "id": "en_male_corey_emo_v2_mars_bigtts",
            "name": "Corey",
            "locale": "en-GB",
        },
        {
            "id": "en_female_nadia_tips_emo_v2_mars_bigtts",
            "name": "Nadia",
            "locale": "en-GB",
        },
        {
            "id": "zh_male_shenyeboke_emo_v2_mars_bigtts",
            "name": "深夜播客",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_yingyujiaoyu_mars_bigtts",
            "name": "Tina老师",
            "locale": "zh-CN/en-GB",
        },
        {
            "id": "ICL_zh_female_wenrounvshen_239eff5e8ffa_tob",
            "name": "温柔女神",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_vv_mars_bigtts",
            "name": "Vivi",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_qinqienvsheng_moon_bigtts",
            "name": "亲切女声",
            "locale": "zh-CN",
        },
        {
            "id": "ICL_zh_male_shenmi_v1_tob",
            "name": "机灵小伙",
            "locale": "zh-CN",
        },
        {
            "id": "ICL_zh_female_wuxi_tob",
            "name": "元气甜妹",
            "locale": "zh-CN",
        },
        {
            "id": "ICL_zh_female_wenyinvsheng_v1_tob",
            "name": "知心姐姐",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_qingyiyuxuan_mars_bigtts",
            "name": "阳光阿辰",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_xudong_conversation_wvae_bigtts",
            "name": "快乐小东",
            "locale": "zh-CN/en-GB",
        },
        {
            "id": "ICL_zh_male_lengkugege_v1_tob",
            "name": "冷酷哥哥",
            "locale": "zh-CN",
        },
        {
            "id": "ICL_zh_female_feicui_v1_tob",
            "name": "纯澈女生",
            "locale": "zh-CN",
        },
        {
            "id": "ICL_zh_female_yuxin_v1_tob",
            "name": "初恋女友",
            "locale": "zh-CN",
        },
        {
            "id": "ICL_zh_female_xnx_tob",
            "name": "贴心闺蜜",
            "locale": "zh-CN",
        },
        {
            "id": "ICL_zh_female_yry_tob",
            "name": "温柔白月光",
            "locale": "zh-CN",
        },
        {
            "id": "ICL_zh_male_BV705_streaming_cs_tob",
            "name": "炀炀",
            "locale": "zh-CN",
        },
        {
            "id": "en_male_jason_conversation_wvae_bigtts",
            "name": "开朗学长",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_sophie_conversation_wvae_bigtts",
            "name": "魅力苏菲",
            "locale": "zh-CN/en-US/es-ES/ja-JP",
        },
        {
            "id": "ICL_zh_female_yilin_tob",
            "name": "贴心妹妹",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_tianmeitaozi_mars_bigtts",
            "name": "甜美桃子",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_qingxinnvsheng_mars_bigtts",
            "name": "清新女声",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_zhixingnvsheng_mars_bigtts",
            "name": "知性女声",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_qingshuangnanda_mars_bigtts",
            "name": "清爽男大",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_linjianvhai_moon_bigtts",
            "name": "邻家女孩",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_yuanboxiaoshu_moon_bigtts",
            "name": "渊博小叔",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_yangguangqingnian_moon_bigtts",
            "name": "阳光青年",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_tianmeixiaoyuan_moon_bigtts",
            "name": "甜美小源",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_qingchezizi_moon_bigtts",
            "name": "清澈梓梓",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_jieshuoxiaoming_moon_bigtts",
            "name": "解说小明",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_kailangjiejie_moon_bigtts",
            "name": "开朗姐姐",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_linjiananhai_moon_bigtts",
            "name": "邻家男孩",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_tianmeiyueyue_moon_bigtts",
            "name": "甜美悦悦",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_xinlingjitang_moon_bigtts",
            "name": "心灵鸡汤",
            "locale": "zh-CN",
        },
        {
            "id": "ICL_zh_female_zhixingwenwan_tob",
            "name": "知性温婉",
            "locale": "zh-CN",
        },
        {
            "id": "ICL_zh_male_nuanxintitie_tob",
            "name": "暖心体贴",
            "locale": "zh-CN",
        },
        {
            "id": "ICL_zh_male_kailangqingkuai_tob",
            "name": "开朗轻快",
            "locale": "zh-CN",
        },
        {
            "id": "ICL_zh_male_huoposhuanglang_tob",
            "name": "活泼爽朗",
            "locale": "zh-CN",
        },
        {
            "id": "ICL_zh_male_shuaizhenxiaohuo_tob",
            "name": "率真小伙",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_wenrouxiaoge_mars_bigtts",
            "name": "温柔小哥",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_cancan_mars_bigtts",
            "name": "灿灿/Shiny",
            "locale": "zh-CN/en-US",
        },
        {
            "id": "zh_female_shuangkuaisisi_moon_bigtts",
            "name": "爽快思思/Skye",
            "locale": "zh-CN/en-US",
        },
        {
            "id": "zh_male_wennuanahu_moon_bigtts",
            "name": "温暖阿虎/Alvin",
            "locale": "zh-CN/en-US",
        },
        {
            "id": "zh_male_shaonianzixin_moon_bigtts",
            "name": "少年梓辛/Brayan",
            "locale": "zh-CN/en-US",
        },
        {
            "id": "ICL_zh_female_wenrouwenya_tob",
            "name": "温柔文雅",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_yueyunv_mars_bigtts",
            "name": "粤语小溏",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_yuzhouzixuan_moon_bigtts",
            "name": "豫州子轩",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_daimengchuanmei_moon_bigtts",
            "name": "呆萌川妹",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_guangxiyuanzhou_moon_bigtts",
            "name": "广西远舟",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_zhoujielun_emo_v2_mars_bigtts",
            "name": "双节棍小哥",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_wanwanxiaohe_moon_bigtts",
            "name": "湾湾小何",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_wanqudashu_moon_bigtts",
            "name": "湾区大叔",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_guozhoudege_moon_bigtts",
            "name": "广州德哥",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_haoyuxiaoge_moon_bigtts",
            "name": "浩宇小哥",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_beijingxiaoye_moon_bigtts",
            "name": "北京小爷",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_jingqiangkanye_moon_bigtts",
            "name": "京腔侃爷/Harmony",
            "locale": "zh-CN/en-US",
        },
        {
            "id": "zh_female_meituojieer_moon_bigtts",
            "name": "妹坨洁儿",
            "locale": "zh-CN",
        },
        {
            "id": "ICL_zh_female_tiaopigongzhu_tob",
            "name": "调皮公主",
            "locale": "zh-CN",
        },
        {
            "id": "ICL_zh_male_shuanglangshaonian_tob",
            "name": "爽朗少年",
            "locale": "zh-CN",
        },
        {
            "id": "ICL_zh_male_tiancaitongzhuo_tob",
            "name": "天才同桌",
            "locale": "zh-CN",
        },
        {
            "id": "en_female_lauren_moon_bigtts",
            "name": "Lauren",
            "locale": "en-US",
        },
        {
            "id": "en_male_campaign_jamal_moon_bigtts",
            "name": "Energetic Male II",
            "locale": "en-US",
        },
        {
            "id": "en_male_chris_moon_bigtts",
            "name": "Gotham Hero",
            "locale": "en-US",
        },
        {
            "id": "en_female_product_darcie_moon_bigtts",
            "name": "Flirty Female",
            "locale": "en-US",
        },
        {
            "id": "en_female_emotional_moon_bigtts",
            "name": "Peaceful Female",
            "locale": "en-US",
        },
        {
            "id": "en_female_nara_moon_bigtts",
            "name": "Nara",
            "locale": "en-US",
        },
        {
            "id": "en_male_bruce_moon_bigtts",
            "name": "Bruce",
            "locale": "en-US",
        },
        {
            "id": "en_male_michael_moon_bigtts",
            "name": "Michael",
            "locale": "en-US",
        },
        {
            "id": "ICL_en_male_cc_sha_v1_tob",
            "name": "Cartoon Chef",
            "locale": "en-US",
        },
        {
            "id": "ICL_zh_female_qingyingduoduo_cs_tob",
            "name": "轻盈朵朵",
            "locale": "zh-CN",
        },
        {
            "id": "ICL_zh_female_wenwanshanshan_cs_tob",
            "name": "温婉珊珊",
            "locale": "zh-CN",
        },
        {
            "id": "ICL_zh_female_reqingaina_cs_tob",
            "name": "热情艾娜",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_kefunvsheng_mars_bigtts",
            "name": "暖阳女声",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_M100_conversation_wvae_bigtts",
            "name": "悠悠君子",
            "locale": "zh-CN/en-US/es-ES",
        },
        {
            "id": "zh_female_maomao_conversation_wvae_bigtts",
            "name": "文静毛毛",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_wenrouxiaoya_moon_bigtts",
            "name": "温柔小雅",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_tiancaitongsheng_mars_bigtts",
            "name": "天才童声",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_sunwukong_mars_bigtts",
            "name": "猴哥",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_peiqi_mars_bigtts",
            "name": "佩奇猪",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_jieshuonansheng_mars_bigtts",
            "name": "磁性解说男声/Morgan",
            "locale": "zh-CN/en-US",
        },
        {
            "id": "zh_female_jitangmeimei_mars_bigtts",
            "name": "鸡汤妹妹/Hope",
            "locale": "zh-CN/en-US",
        },
        {
            "id": "zh_female_tiexinnvsheng_mars_bigtts",
            "name": "贴心女声/Candy",
            "locale": "zh-CN/en-US",
        },
        {
            "id": "zh_female_mengyatou_mars_bigtts",
            "name": "萌丫头/Cutey",
            "locale": "zh-CN/en-US",
        },
        {
            "id": "zh_male_changtianyi_mars_bigtts",
            "name": "悬疑解说",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_ruyaqingnian_mars_bigtts",
            "name": "儒雅青年",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_baqiqingshu_mars_bigtts",
            "name": "霸气青叔",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_qingcang_mars_bigtts",
            "name": "擎苍",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_fanjuanqingnian_mars_bigtts",
            "name": "反卷青年",
            "locale": "zh-CN",
        },
    ),
    VOLCENGINE_TTS_MODEL_SEED_2_0: (
        {
            "id": "zh_female_vv_uranus_bigtts",
            "name": "Vivi 2.0",
            "locale": "zh-CN/ja-JP/id-ID/es-MX",
        },
        {
            "id": "zh_female_xiaohe_uranus_bigtts",
            "name": "小何 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_m191_uranus_bigtts",
            "name": "云舟 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_taocheng_uranus_bigtts",
            "name": "小天 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_liufei_uranus_bigtts",
            "name": "刘飞 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_sophie_uranus_bigtts",
            "name": "魅力苏菲 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_qingxinnvsheng_uranus_bigtts",
            "name": "清新女声 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_cancan_uranus_bigtts",
            "name": "知性灿灿 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_sajiaoxuemei_uranus_bigtts",
            "name": "撒娇学妹 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_tianmeixiaoyuan_uranus_bigtts",
            "name": "甜美小源 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_tianmeitaozi_uranus_bigtts",
            "name": "甜美桃子 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_shuangkuaisisi_uranus_bigtts",
            "name": "爽快思思 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_peiqi_uranus_bigtts",
            "name": "佩奇猪 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_linjianvhai_uranus_bigtts",
            "name": "邻家女孩 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_shaonianzixin_uranus_bigtts",
            "name": "少年梓辛/Brayan 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_sunwukong_uranus_bigtts",
            "name": "猴哥 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_yingyujiaoxue_uranus_bigtts",
            "name": "Tina老师 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_kefunvsheng_uranus_bigtts",
            "name": "暖阳女声 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_xiaoxue_uranus_bigtts",
            "name": "儿童绘本 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_dayi_uranus_bigtts",
            "name": "大壹 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_mizai_uranus_bigtts",
            "name": "黑猫侦探社咪仔 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_jitangnv_uranus_bigtts",
            "name": "鸡汤女 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_meilinvyou_uranus_bigtts",
            "name": "魅力女友 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_liuchangnv_uranus_bigtts",
            "name": "流畅女声 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_ruyayichen_uranus_bigtts",
            "name": "儒雅逸辰 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "en_male_tim_uranus_bigtts",
            "name": "Tim",
            "locale": "en-US",
        },
        {
            "id": "en_female_dacey_uranus_bigtts",
            "name": "Dacey",
            "locale": "en-US",
        },
        {
            "id": "en_female_stokie_uranus_bigtts",
            "name": "Stokie",
            "locale": "en-US",
        },
        {
            "id": "zh_female_xueayi_saturn_bigtts",
            "name": "儿童绘本",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_dayi_saturn_bigtts",
            "name": "大壹",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_mizai_saturn_bigtts",
            "name": "黑猫侦探社咪仔",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_jitangnv_saturn_bigtts",
            "name": "鸡汤女",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_meilinvyou_saturn_bigtts",
            "name": "魅力女友",
            "locale": "zh-CN",
        },
        {
            "id": "zh_female_santongyongns_saturn_bigtts",
            "name": "流畅女声",
            "locale": "zh-CN",
        },
        {
            "id": "zh_male_ruyayichen_saturn_bigtts",
            "name": "儒雅逸辰",
            "locale": "zh-CN",
        },
        {
            "id": "saturn_zh_female_keainvsheng_tob",
            "name": "可爱女生",
            "locale": "zh-CN",
        },
        {
            "id": "saturn_zh_female_tiaopigongzhu_tob",
            "name": "调皮公主",
            "locale": "zh-CN",
        },
        {
            "id": "saturn_zh_male_shuanglangshaonian_tob",
            "name": "爽朗少年",
            "locale": "zh-CN",
        },
        {
            "id": "saturn_zh_male_tiancaitongzhuo_tob",
            "name": "天才同桌",
            "locale": "zh-CN",
        },
        {
            "id": "saturn_zh_female_cancan_tob",
            "name": "知性灿灿",
            "locale": "zh-CN",
        },
        {
            "id": "saturn_zh_female_qingyingduoduo_cs_tob",
            "name": "轻盈朵朵 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "saturn_zh_female_wenwanshanshan_cs_tob",
            "name": "温婉珊珊 2.0",
            "locale": "zh-CN",
        },
        {
            "id": "saturn_zh_female_reqingaina_cs_tob",
            "name": "热情艾娜 2.0",
            "locale": "zh-CN",
        },
    ),
}


def normalize_volcengine_tts_model_name(value: Any) -> str:
    normalized = str(value or "").strip() or VOLCENGINE_TTS_DEFAULT_MODEL_NAME
    if normalized in VOLCENGINE_TTS_MODEL_RESOURCE_MAP:
        return normalized
    return VOLCENGINE_TTS_DEFAULT_MODEL_NAME


def resolve_volcengine_tts_resource_id(model_name: Any) -> str:
    normalized_model = normalize_volcengine_tts_model_name(model_name)
    return VOLCENGINE_TTS_MODEL_RESOURCE_MAP.get(
        normalized_model, VOLCENGINE_TTS_DEFAULT_RESOURCE_ID
    )


def list_volcengine_tts_voices(model_name: Any) -> list[dict[str, str]]:
    normalized_model = normalize_volcengine_tts_model_name(model_name)
    voices = VOLCENGINE_TTS_MODEL_VOICE_MAP.get(normalized_model)
    if not voices:
        voices = VOLCENGINE_TTS_MODEL_VOICE_MAP.get(VOLCENGINE_TTS_DEFAULT_MODEL_NAME, ())
    return [dict(item) for item in voices]


def resolve_default_volcengine_tts_voice_type(model_name: Any) -> str:
    voices = list_volcengine_tts_voices(model_name)
    if voices:
        voice_id = str(voices[0].get("id") or "").strip()
        if voice_id:
            return voice_id
    return VOLCENGINE_TTS_DEFAULT_VOICE_TYPE


def is_volcengine_tts_voice_supported(model_name: Any, voice_type: Any) -> bool:
    normalized_voice = str(voice_type or "").strip()
    if not normalized_voice:
        return False
    return any(
        normalized_voice == str(item.get("id") or "").strip()
        for item in list_volcengine_tts_voices(model_name)
    )
