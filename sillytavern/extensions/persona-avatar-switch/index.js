/**
 * Axiodrasil Persona Avatar Switch
 * ---------------------------------
 * p3-avatar-switch-decision 选定方案 2（轻量自定义扩展）的实现。
 *
 * 背景：内阁只在酒馆里建了一张「内阁」角色卡（不用 Group Chat 多角色卡路线，
 * 避免牵扯"该谁说话"的控制权）。但每一轮回复的第一段文字是后端 `_execute_turn`
 * 已经生成好的人格前缀，形如 `[bina]: ...`、`[bit]: ...`、`[qianjin]: ...`。
 * 这个扩展做两件事：
 *   1. 把可见气泡里的 `[xxx]:` 前缀去掉（它是路由元数据，不是人设台词）。
 *   2. 把 Character Expressions 插件（Classification Source = Local）渲染出来
 *      的表情图，从默认的 `characters/内阁/<emotion>.png` 重定向到
 *      `characters/内阁/<persona>/<emotion>.png`，从而在「同一张情绪分类结果」下
 *      展示不同人格自己的表情图集（对应 sillytavern/sprites/<persona>/ 里的素材）。
 *
 * 已知限制 / 请知悉：
 * - 本文件是在没有真实 SillyTavern 运行环境下、基于官方文档与开源源码阅读写出的
 *   「最佳努力」实现，用到的事件名 `CHARACTER_MESSAGE_RENDERED` 与 DOM 选择器
 *   `#expression-image` / `.mes[mesid] .mes_text` 是编写时查证到的公开、稳定接口，
 *   但 ST 版本演进可能会改动内部实现。如果装上之后头像不切换/文本前缀没被吃掉，
 *   请打开浏览器开发者工具，确认这两个选择器在你的版本里是否仍然对应正确的元素，
 *   按需调整下面的常量。
 * - 只处理 11 个 BIOS 人格 + jean 这 12 个已知前缀；未知前缀不做任何改写，原样显示。
 */

(function () {
    const MODULE_NAME = 'axiodrasil-persona-avatar-switch';

    // 需与 agents/router.py 的 PERSONA_META / sillytavern/sprites/<persona>/ 目录名一致
    const KNOWN_PERSONAS = [
        'bina', 'bit', 'taki', 'chizheng', 'tianji', 'fukucho',
        'vinci', 'planck', 'jiafa', 'qianjin', 'boming', 'jean',
    ];

    // Character Expressions 插件渲染表情图的 <img> 元素选择器（见文件头部说明）
    const EXPRESSION_IMG_SELECTOR = '#expression-image';

    function extractPersona(messageText) {
        const match = /^\s*\[([a-zA-Z]+)\]\s*[:：]/.exec(messageText || '');
        if (!match) return null;
        const persona = match[1].toLowerCase();
        return KNOWN_PERSONAS.includes(persona) ? persona : null;
    }

    function stripPersonaPrefix(messageText) {
        return (messageText || '').replace(/^\s*\[[a-zA-Z]+\]\s*[:：]\s*/, '');
    }

    /**
     * 把 Character Expressions 当前渲染出的图片路径，从
     * `.../characters/<角色文件夹>/<emotion>.png` 重写为
     * `.../characters/<角色文件夹>/<persona>/<emotion>.png`。
     * 依赖酒馆「Sprite Folder Override」同款的子目录约定，但这里按消息动态改写，
     * 不需要用户手动切换设置。
     */
    function redirectExpressionImageToPersona(persona) {
        const img = document.querySelector(EXPRESSION_IMG_SELECTOR);
        if (!img || !img.src) return;

        try {
            const url = new URL(img.src);
            const marker = '/characters/';
            const idx = url.pathname.indexOf(marker);
            if (idx === -1) return;

            const after = url.pathname.slice(idx + marker.length);
            const segments = after.split('/').filter(Boolean);
            if (segments.length < 2) return;

            const charFolder = segments[0];
            const fileName = segments[segments.length - 1];
            const newPath = `${url.pathname.slice(0, idx + marker.length)}${charFolder}/${persona}/${fileName}`;

            if (url.pathname !== newPath) {
                url.pathname = newPath;
                img.src = url.toString();
            }
        } catch (e) {
            console.warn(`[${MODULE_NAME}] 重定向表情图路径失败:`, e);
        }
    }

    function onMessageRendered(messageId) {
        try {
            const context = SillyTavern.getContext();
            const message = context.chat && context.chat[messageId];
            if (!message || message.is_user) return;

            const persona = extractPersona(message.mes);
            if (!persona) return;

            const messageElement = document.querySelector(
                `.mes[mesid="${messageId}"] .mes_text`
            );
            if (messageElement && messageElement.textContent.trim().startsWith('[')) {
                messageElement.textContent = stripPersonaPrefix(message.mes);
            }

            redirectExpressionImageToPersona(persona);
        } catch (e) {
            console.warn(`[${MODULE_NAME}] 处理消息渲染事件失败:`, e);
        }
    }

    function init() {
        const context = SillyTavern.getContext();
        const { eventSource, event_types } = context;

        if (!eventSource || !event_types || !event_types.CHARACTER_MESSAGE_RENDERED) {
            console.warn(`[${MODULE_NAME}] 未找到 CHARACTER_MESSAGE_RENDERED 事件，扩展未启用。`);
            return;
        }

        eventSource.on(event_types.CHARACTER_MESSAGE_RENDERED, onMessageRendered);
        console.log(`[${MODULE_NAME}] 已加载，监听 CHARACTER_MESSAGE_RENDERED。`);
    }

    if (typeof SillyTavern !== 'undefined') {
        init();
    } else {
        console.warn(`[axiodrasil-persona-avatar-switch] 未检测到 SillyTavern 全局对象，扩展未初始化。`);
    }
})();
