/**
 * Axiodrasil Persona Avatar Switch (LEGACY — 单卡「内阁」路线)
 * ---------------------------------
 * 酒馆已改为 Group Chat（每人设一张卡，由酒馆调度谁发言），本扩展仅保留给
 * 旧版单卡「内阁」+ `[persona]:` 前缀头像切换。Group Chat 路径不需要本扩展。
 *
 * 背景（历史）：内阁曾在酒馆里建一张「内阁」角色卡（不用 Group Chat），
 * 每一轮回复第一段是后端 `_execute_turn` 生成的人格前缀，形如 `[bina]: ...`。
 * 这个扩展做两件事：
 *   1. 把可见气泡里的 `[xxx]:` 前缀去掉。
 *   2. 把 Character Expressions 表情图重定向到 `characters/内阁/<persona>/`。
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
