#!/usr/bin/env python3
"""
批量生成单人/双人讲述者预设角色图片。

默认使用：
- Provider: openai_chat (CLIProxyAPI)
- Model: gemini-3-pro-image-preview

输出目录：
- storage/reference-library/builtin
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.providers import get_image_provider


@dataclass(frozen=True)
class PresetImageTask:
    filename: str
    character_name: str
    appearance: str


TASKS: list[PresetImageTask] = [
    PresetImageTask(
        "fandebiao.png",
        "范德彪",
        "四十岁左右中年男性，圆脸微肉、鼻梁略宽，浓黑短发向后梳并留细碎发，眉峰上挑，眼神机灵带笑。体型中等偏壮。上身深灰短夹克叠黑色高领内搭，下身深色直筒长裤，脚穿黑色皮靴。全身站姿放松但重心稳定，双肩微开，像见惯世面的市井能人，喜感鲜明且辨识度高。",
    ),
    PresetImageTask(
        "liyunlong.png",
        "李云龙",
        "三十五岁左右硬朗男性，短寸发贴头利落，额角清爽，眉骨突出、下颌线硬，目光锋利。体型高壮、肩背宽厚。上身军绿色立领夹克配深色内搭，下身深灰工装长裤，脚穿黑色作战靴。全身站姿笔直前压，双臂自然下垂但张力明显，呈现一线指挥官的冷硬气场与强攻击性。",
    ),
    PresetImageTask(
        "meichangsu.png",
        "梅长苏",
        "三十岁左右清瘦男性，肤色偏白，乌发高束成冠并贴服顺直，眉眼狭长，鼻梁挺直，唇线平稳。体型修长偏薄。上身月白交领长衫外搭深色披肩，腰间窄带收束，下身同色长裤，脚穿素色布靴。全身站姿端正克制，手部自然收拢，整体沉静理性，谋士气质清晰且层次分明。",
    ),
    PresetImageTask(
        "jixiaolan.png",
        "纪晓岚",
        "四十岁左右文士男性，前额光洁、后束长辫，脸型偏长，眼尾微挑，唇角常带含笑反讽。体型中等偏瘦。上身墨蓝官服外搭黑色马褂，领口与袖缘平整挺括，下身深色长裤，脚穿黑布官靴。全身站姿从容挺直、下颌微抬，温雅外表下带机敏锋芒，士大夫神韵与讥诮感并存。",
    ),
    PresetImageTask(
        "hairui.png",
        "海瑞",
        "五十岁左右清官男性，面容清瘦、法令纹清晰，发髻规整并戴乌纱帽，眉眼沉稳不怒自威。体型偏瘦但骨架端正。上身深蓝官袍配黑色束带，衣摆垂直利落，下身同色长摆，脚穿黑色官靴。全身站姿中轴笔直、双手自然垂放，整体克己肃穆，威严与原则感非常明确。",
    ),
    PresetImageTask(
        "lixiaoyao.png",
        "李逍遥",
        "二十岁出头青年侠客，黑发高马尾配细碎刘海，眉眼清亮，鼻梁秀挺，笑意自信。体型修长精干、动作感轻快。上身靛蓝短襟侠客服叠浅色内衬，腰间系皮质束带并挂小囊，下身深色窄腿裤，脚穿轻便短靴。全身站姿微前倾、肩颈放松，少年侠气与冒险气息突出，形象明快。",
    ),
    PresetImageTask(
        "houliangping.png",
        "侯亮平",
        "四十岁左右现代男性，短发利落贴头，眉骨略高，面部线条硬朗，唇线紧收，目光审视感强。体型高瘦挺拔。上身深炭灰西装外套配黑色衬衫，领口干净，下身同色西裤，脚穿黑色皮鞋。全身站姿挺直克制、肩线平直，呈现高压调查者的理性锋利与不回避冲突的压迫感。",
    ),
    PresetImageTask(
        "baozheng.png",
        "包拯",
        "四十岁左右古代官员男性，肤色偏深，方脸厚眉，鼻翼宽，目光沉稳坚硬；发冠规整并戴黑色官帽。体型中等偏壮。上身深绛官服配黑色护领与宽袖，衣摆垂坠整齐，下身深色长裤，脚穿黑色官靴。全身站姿挺直稳重、肩线平衡，秩序感与压场力强，整体气质严整不张扬。",
    ),
    PresetImageTask(
        "gongsunce.png",
        "公孙策",
        "三十岁左右古代文士男性，面容清秀，眉形细长，眼神专注敏捷，发髻整齐无散发。体型修长偏瘦。上身浅青长衫叠米色内领，衣料轻薄有层次，腰间窄带收束，下身同色长裤，脚穿浅色布靴。全身站姿端正略前倾，手势克制，书卷气与信息处理敏锐感同时突出。",
    ),
    PresetImageTask(
        "anxin.png",
        "安欣",
        "三十多岁现代男性，短发平整、额头干净，颧骨略高，下颌线利落，眼神警觉而克制。体型精干结实。上身深蓝夹克配黑色内搭，下身深灰直筒长裤，脚穿深色运动靴。全身站姿紧致微前压，肩颈收束、重心稳定，整体呈现守规则但不退让的对抗气质，冷静而有韧性。",
    ),
    PresetImageTask(
        "gaoqiqiang.png",
        "高启强",
        "四十岁左右现代男性，黑发背头整齐发亮，眉眼深、鼻梁直，嘴角带克制笑意。体型中高偏瘦。上身深灰修身西装配白衬衫，下身同色西裤，脚穿亮面黑皮鞋。全身站姿看似放松但重心前置，肩线平稳、手部收敛，显出强掌控欲和不动声色的压迫感，气场强势。",
    ),
    PresetImageTask(
        "lidakang.png",
        "李达康",
        "四十岁左右现代男性，短发干净利落、发际线清晰，眉心轻皱，视线直给。体型中等偏瘦。上身深藏青西装配白衬衫与暗纹领带，衣装贴合，下身同色西裤，脚穿黑色商务皮鞋。全身站姿挺拔、下巴微收，状态紧绷有序，呈现高压决策者的权威感与执行力度。",
    ),
    PresetImageTask(
        "sharuijin.png",
        "沙瑞金",
        "五十岁左右现代男性，头发后梳整齐，额角略有岁月痕迹，面部线条平稳，眼神沉静。体型中等偏壮。上身深灰商务夹克配浅色衬衣，下身深色西裤，脚穿棕黑商务皮鞋。全身站姿放松但背部挺直，双肩自然展开，整体老练审慎、稳定可信，兼具亲和与分寸感。",
    ),
    PresetImageTask(
        "tangren.png",
        "唐仁",
        "三十岁左右现代男性，短卷发蓬松有层次，眉眼灵活，笑纹明显，表情外放。体型中等偏瘦。上身浅棕休闲外套配白色内搭与细项链，下身深色修身长裤，脚穿浅色休闲鞋。全身站姿轻快有弹性，身体微侧、重心灵活，舞台存在感强，亲和感与机敏感都很突出。",
    ),
    PresetImageTask(
        "qinfeng.png",
        "秦风",
        "二十多岁现代青年男性，黑色短发服帖，五官清晰，目光聚焦且冷静。体型修长偏瘦。上身深色针织上衣外搭简洁夹克，线条干净，下身深灰直筒长裤，脚穿低调深色运动鞋。全身站姿稳定克制、肩线平直，动作信息量低，整体呈现精确拆解问题的理性专家气质。",
    ),
    PresetImageTask(
        "baizhantang.png",
        "白展堂",
        "二十多岁古风男性，高束发利落，额前留短碎发，眼神机灵，笑纹明显。体型轻巧精干。上身深蓝短打并配黑色护腕与腰封，衣摆利落，下身黑色束脚长裤，脚穿软底快靴。全身站姿略侧身、肩线灵活，手部自然外展，江湖人的敏捷感与轻松戏感非常鲜明。",
    ),
    PresetImageTask(
        "guofurong.png",
        "郭芙蓉",
        "二十多岁古风女性，高发髻紧致利落，额前短碎发贴脸，眼睛大而明亮，眉形上扬。体型纤细且有力量感。上身橙红短袄配浅色交领内衫，下身米白长裙并系窄腰封，脚穿绣纹短靴。全身站姿挺拔利落、胸背展开，神情外放直接，整体泼辣明快且极具辨识度。",
    ),
    PresetImageTask(
        "yanchixia.png",
        "燕赤霞",
        "三十岁左右古风侠客男性，高束发并插木簪，眉峰高、眼神锐利，面部棱角清楚。体型高大结实。上身黑色道袍叠深褐披肩与宽腰带，层次厚重，下身深色长裤，脚穿厚底黑靴。全身站姿开阔稳重、双腿分立，压迫感和硬派气质明显，形象强势但不凌乱。",
    ),
    PresetImageTask(
        "ningcaichen.png",
        "宁采臣",
        "二十多岁古风书生男性，半束长发自然垂落，面容清秀，眼神温和却敏捷。体型偏瘦。上身浅米长衫外搭细纹轻披，领口整洁，腰间细带收束，下身同色长裤，脚穿浅棕布履。全身站姿微收但不怯、肩线略内敛，呈现温和外表下的机敏反差与书生气。",
    ),
    PresetImageTask(
        "wangmiao.png",
        "汪淼",
        "三十多岁现代理工男性，短发平整、额头开阔，五官规整，神情克制。体型中等偏瘦。上身灰蓝衬衫外搭深色功能夹克，配色低饱和，下身炭灰长裤，脚穿深色系带鞋。全身站姿中正稳健、双肩平衡，注重秩序与细节，体现严谨理性、重事实的专业气质。",
    ),
    PresetImageTask(
        "yewenjie.png",
        "叶文洁",
        "六十岁左右现代女性，短发贴头规整，发丝银黑相间，眼神沉静有距离感。体型偏瘦、姿态克制。上身深色素雅针织上衣外搭无图案长外套，下身深色直筒长裤，脚穿低跟皮鞋。全身站姿稳定内敛、重心平衡，神情严谨，整体高智冷静并带克制的威压感。",
    ),
    PresetImageTask(
        "direnjie.png",
        "狄仁杰",
        "四十岁左右古代名臣男性，眉眼深邃，胡须修整整洁，神态凝重，官帽佩戴端正。体型中等偏壮。上身深紫官服配黑色内衬与宽袖，纹理克制，下身深色长裤，脚穿黑色官靴。全身站姿沉稳如山、目光停留有力，逻辑主导者的威严与权衡气质十分突出。",
    ),
    PresetImageTask(
        "liyuanfang.png",
        "李元芳",
        "三十岁左右古代护卫男性，短发束冠利落，面部干净，眼神专注警醒。体型高瘦结实。上身深青武官服配皮质护肩和护臂，腰间束带紧实，下身深色束腿裤，脚穿硬底战靴。全身站姿挺直利落、腿部支撑明确，轮廓干净，执行型武者的可靠感与纪律性很强。",
    ),
    PresetImageTask(
        "xiaolongnv.png",
        "小龙女",
        "二十多岁古风女性，乌黑长发垂至腰间，仅以素银发簪固定，眉眼清透柔和。体型纤细修长。上身素白轻纱交领长衣，下身同色曳地长裙，腰间细带收束，衣褶细密流畅，脚穿白色软底绣鞋。全身站姿轻柔安静、颈肩舒展，气质清冷宁定，具有温和包裹感。",
    ),
    PresetImageTask(
        "yangguo.png",
        "杨过",
        "二十多岁古风青年男性，长发半束并留自然散发，五官温润，眼神柔和专注。体型修长匀称。上身灰青侠客服配素色内衬与窄腰带，细节简洁，下身深色长裤，脚穿灰色软皮靴。全身站姿端正沉静、肩背舒展，气质真诚可靠，传达可依靠的稳定支持感。",
    ),
]


def build_prompt(task: PresetImageTask) -> str:
    return (
        f"角色名称：{task.character_name}。"
        f"外观设定：{task.appearance}"
        "请生成单人角色立绘，全身站姿构图，正面或微侧面，人物主体清晰居中。"
        "日系动漫风格，正常头身比，不要大头，线条干净，色彩明快，角色辨识度高。"
        "背景简洁纯色或轻虚化，动漫风格的灯光效果，阴影柔和，不要复杂场景。"
        "不要出现任何可读文字、标题、字幕、水印、logo、UI元素。"
    )


async def generate_one(
    provider, output_dir: Path, task: PresetImageTask, force: bool
) -> tuple[str, str]:
    output_path = output_dir / task.filename
    if output_path.exists() and not force:
        return task.filename, "skipped"

    prompt = build_prompt(task)
    await provider.generate(
        prompt=prompt,
        output_path=output_path,
        aspect_ratio="1:1",
        image_size="1K",
    )
    return task.filename, "generated"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Generate narrator preset images")
    parser.add_argument("--force", action="store_true", help="Regenerate even if file exists")
    parser.add_argument("--concurrency", type=int, default=1, help="Generation concurrency")
    parser.add_argument("--base-url", type=str, default="", help="CLIProxyAPI base url")
    parser.add_argument("--api-key", type=str, default="", help="CLIProxyAPI api key")
    args = parser.parse_args()

    output_dir = (
        Path(settings.storage_path).expanduser().resolve() / "reference-library" / "builtin"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    resolved_base_url = (
        args.base_url.strip()
        or settings.image_openai_base_url
        or settings.text_openai_base_url
        or "https://sanbeimao-cliproxyapi.hf.space"
    )
    resolved_api_key = (
        args.api_key.strip() or settings.image_openai_api_key or settings.text_openai_api_key or ""
    )

    provider = get_image_provider(
        "openai_chat",
        base_url=resolved_base_url,
        api_key=resolved_api_key,
        model="gemini-3-pro-image-preview",
        aspect_ratio="1:1",
        image_size="1K",
    )

    print(f"[PresetImages] output_dir={output_dir}")
    print(
        "[PresetImages] provider=openai_chat model=gemini-3-pro-image-preview"
        f" base_url={resolved_base_url}"
    )
    print(
        f"[PresetImages] tasks={len(TASKS)} force={args.force} concurrency={max(1, args.concurrency)}"
    )
    if not resolved_api_key:
        print("[PresetImages] WARNING: api_key 为空，目标网关可能返回 401")

    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    results: list[tuple[str, str]] = []

    async def worker(task: PresetImageTask) -> None:
        async with semaphore:
            try:
                filename, status = await generate_one(provider, output_dir, task, args.force)
                print(f"[PresetImages] {filename}: {status}")
                results.append((filename, status))
            except Exception as e:
                filename = task.filename
                status = "failed"
                print(f"[PresetImages] {filename}: {status} ({e})")
                results.append((filename, status))

    await asyncio.gather(*(worker(task) for task in TASKS))

    generated = sum(1 for _, status in results if status == "generated")
    skipped = sum(1 for _, status in results if status == "skipped")
    failed = sum(1 for _, status in results if status == "failed")
    print(
        f"[PresetImages] done: generated={generated} skipped={skipped} failed={failed} total={len(results)}"
    )


if __name__ == "__main__":
    asyncio.run(main())
