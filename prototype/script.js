// 页面切换功能
function showPage(pageId) {
    document.querySelectorAll('.page').forEach(page => {
        page.classList.remove('active');
    });
    document.getElementById(pageId).classList.add('active');
}

// Toast提示功能
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    toast.style.cssText = `
        position: fixed;
        bottom: 2rem;
        left: 50%;
        transform: translateX(-50%);
        background-color: var(--color-bg-2);
        color: var(--color-text-primary);
        padding: 0.75rem 1.5rem;
        border-radius: var(--radius-md);
        box-shadow: var(--shadow-md);
        z-index: 2000;
        animation: slideUp 0.2s ease-out;
        max-width: 90%;
        text-align: center;
        border: 1px solid var(--color-border);
    `;
    
    if (type === 'success') toast.style.backgroundColor = 'rgba(var(--color-success-rgb), 0.9)';
    if (type === 'error') toast.style.backgroundColor = 'rgba(var(--color-danger-rgb), 0.9)';
    if (type === 'warning') toast.style.backgroundColor = 'rgba(var(--color-warning-rgb), 0.9)';
    if (type === 'success' || type === 'error' || type === 'warning') toast.style.color = 'white';
    
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideDown 0.2s ease-out';
        setTimeout(() => {
            document.body.removeChild(toast);
        }, 200);
    }, 2500);
}

// 添加动画样式
const style = document.createElement('style');
style.textContent = `
    @keyframes slideUp {
        from { transform: translate(-50%, 100%); opacity: 0; }
        to { transform: translate(-50%, 0); opacity: 1; }
    }
    @keyframes slideDown {
        from { transform: translate(-50%, 0); opacity: 1; }
        to { transform: translate(-50%, 100%); opacity: 0; }
    }
`;
document.head.appendChild(style);

// 弹窗控制
const createRoomModal = document.getElementById('createRoomModal');

function openModal(modalId) {
    document.getElementById(modalId).classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeModal(modalId) {
    document.getElementById(modalId).classList.remove('active');
    document.body.style.overflow = 'auto';
}

// 弹窗关闭按钮
document.querySelectorAll('.modal-close, .modal-cancel').forEach(btn => {
    btn.addEventListener('click', () => {
        closeModal('createRoomModal');
    });
});

// 点击遮罩关闭弹窗
createRoomModal.addEventListener('click', (e) => {
    if (e.target === createRoomModal) {
        closeModal('createRoomModal');
    }
});

// 大厅页交互
document.getElementById('createRoomBtn').addEventListener('click', () => {
    openModal('createRoomModal');
});

// 创建房间确认
document.querySelector('#createRoomModal .btn-primary').addEventListener('click', () => {
    closeModal('createRoomModal');
    showToast('房间创建成功！', 'success');
    setTimeout(() => {
        showPage('roomPage');
    }, 400);
});

// 房间页交互
document.getElementById('backToHall').addEventListener('click', () => {
    showPage('hallPage');
});

let isReady = false;
document.getElementById('readyBtn').addEventListener('click', () => {
    isReady = !isReady;
    const btn = document.getElementById('readyBtn');
    const readyTag = document.querySelector('.current-player .ready-tag');
    
    if (isReady) {
        btn.textContent = '取消准备';
        btn.classList.remove('btn-primary');
        btn.classList.add('btn-secondary');
        readyTag.textContent = '已准备';
        readyTag.classList.remove('not-ready');
        document.querySelector('.current-player').classList.add('ready');
        showToast('已准备', 'success');
        
        // 模拟所有玩家准备完成，显示开始游戏按钮
        setTimeout(() => {
            document.getElementById('readyBtn').style.display = 'none';
            document.getElementById('startGameBtn').style.display = 'block';
        }, 800);
    } else {
        btn.textContent = '准备';
        btn.classList.remove('btn-secondary');
        btn.classList.add('btn-primary');
        readyTag.textContent = '未准备';
        readyTag.classList.add('not-ready');
        document.querySelector('.current-player').classList.remove('ready');
        showToast('已取消准备', 'info');
        
        document.getElementById('readyBtn').style.display = 'block';
        document.getElementById('startGameBtn').style.display = 'none';
    }
});

// 开始游戏
document.getElementById('startGameBtn').addEventListener('click', () => {
    showToast('游戏即将开始...', 'success');
    setTimeout(() => {
        showPage('gamePage');
        initGame();
    }, 800);
});

// 对局页逻辑
let countdownInterval = null;
let selectedTarget = null;

function initGame() {
    // 显示夜晚遮罩
    const nightOverlay = document.getElementById('nightOverlay');
    nightOverlay.classList.add('active');
    
    // 3秒后隐藏夜晚遮罩
    setTimeout(() => {
        nightOverlay.classList.remove('active');
        startCountdown(60);
        simulateChatMessages();
    }, 2500);
    
    // 玩家选择功能
    document.querySelectorAll('.player-card-vertical.selectable').forEach(player => {
        player.addEventListener('click', () => {
            // 移除之前的选中状态
            document.querySelectorAll('.player-card-vertical.selectable').forEach(p => {
                p.style.borderColor = 'var(--color-border)';
                p.style.backgroundColor = 'var(--color-bg-2)';
            });
            
            // 设置当前选中
            player.style.borderColor = 'rgba(var(--color-primary-rgb), 0.4)';
            player.style.backgroundColor = 'rgba(var(--color-primary-rgb), 0.08)';
            
            selectedTarget = player.querySelector('.player-name-v').textContent;
            document.getElementById('selectedTarget').textContent = selectedTarget;
            document.getElementById('confirmKillBtn').disabled = false;
        });
    });
}

// 倒计时功能
function startCountdown(seconds) {
    let timeLeft = seconds;
    const countdownEl = document.querySelector('.countdown-number');
    
    if (countdownInterval) clearInterval(countdownInterval);
    
    countdownInterval = setInterval(() => {
        timeLeft--;
        countdownEl.textContent = timeLeft;
        
        if (timeLeft <= 0) {
            clearInterval(countdownInterval);
            showToast('时间到，行动已自动确认', 'warning');
            setTimeout(() => {
                showPage('resultPage');
            }, 1200);
        }
    }, 1000);
}

// 模拟聊天消息
function simulateChatMessages() {
    const messages = [
        { sender: '玩家1（狼人）', content: '我们刀玩家5吧，他看起来像预言家', delay: 800 },
        { sender: '你', content: '同意，我也觉得他有身份', delay: 2000, isYou: true },
        { sender: '玩家1（狼人）', content: '那就刀他，没问题', delay: 3500 }
    ];
    
    const chatArea = document.querySelector('.chat-area');
    
    messages.forEach(msg => {
        setTimeout(() => {
            const messageEl = document.createElement('div');
            messageEl.className = `message wolf-whisper ${msg.isYou ? 'you' : ''}`;
            
            if (!msg.isYou) {
                messageEl.innerHTML = `
                    <div class="avatar avatar-sm">
                        <img src="https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=avatar%20wolf%20line%20art&image_size=square" alt="玩家头像">
                    </div>
                    <div class="message-bubble">
                        <span class="sender-name">${msg.sender}</span>
                        <p>${msg.content}</p>
                    </div>
                `;
            } else {
                messageEl.innerHTML = `
                    <div class="message-bubble">
                        <p>${msg.content}</p>
                    </div>
                    <div class="avatar avatar-sm">
                        <img src="https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=avatar%20wolf%20line%20art&image_size=square" alt="玩家头像">
                    </div>
                `;
            }
            
            chatArea.appendChild(messageEl);
            chatArea.scrollTop = chatArea.scrollHeight;
        }, msg.delay);
    });
}

// 确认击杀
document.getElementById('confirmKillBtn').addEventListener('click', () => {
    if (!selectedTarget) {
        showToast('请先选择击杀目标', 'warning');
        return;
    }
    
    showToast(`已确认击杀${selectedTarget}`, 'success');
    
    if (countdownInterval) clearInterval(countdownInterval);
    
    // 显示夜晚遮罩
    const nightOverlay = document.getElementById('nightOverlay');
    nightOverlay.classList.add('active');
    
    setTimeout(() => {
        showPage('resultPage');
        nightOverlay.classList.remove('active');
    }, 1500);
});

// 发送聊天消息
document.querySelector('.chat-input-area .btn-primary').addEventListener('click', () => {
    const input = document.querySelector('.chat-input-area .input');
    const content = input.value.trim();
    
    if (content) {
        const chatArea = document.querySelector('.chat-area');
        const messageEl = document.createElement('div');
        messageEl.className = 'message wolf-whisper you';
        messageEl.innerHTML = `
            <div class="message-bubble">
                <p>${content}</p>
            </div>
            <div class="avatar avatar-sm">
                <img src="https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=avatar%20wolf%20line%20art&image_size=square" alt="玩家头像">
            </div>
        `;
        
        chatArea.appendChild(messageEl);
        chatArea.scrollTop = chatArea.scrollHeight;
        input.value = '';
    }
});

// 回车发送消息
document.querySelector('.chat-input-area .input').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        document.querySelector('.chat-input-area .btn-primary').click();
    }
});

// 结算页交互
document.getElementById('playAgainBtn').addEventListener('click', () => {
    showToast('正在返回房间...', 'success');
    setTimeout(() => {
        showPage('roomPage');
        // 重置准备状态
        isReady = false;
        document.getElementById('readyBtn').textContent = '准备';
        document.getElementById('readyBtn').classList.remove('btn-secondary');
        document.getElementById('readyBtn').classList.add('btn-primary');
        document.querySelector('.current-player .ready-tag').textContent = '未准备';
        document.querySelector('.current-player .ready-tag').classList.add('not-ready');
        document.querySelector('.current-player').classList.remove('ready');
        document.getElementById('readyBtn').style.display = 'block';
        document.getElementById('startGameBtn').style.display = 'none';
        
        // 重置游戏状态
        if (countdownInterval) clearInterval(countdownInterval);
        selectedTarget = null;
        document.getElementById('selectedTarget').textContent = '未选择';
        document.getElementById('confirmKillBtn').disabled = true;
        document.querySelectorAll('.player-card-vertical.selectable').forEach(p => {
            p.style.borderColor = 'var(--color-border)';
            p.style.backgroundColor = 'var(--color-bg-2)';
        });
    }, 800);
});

document.getElementById('backToHallBtn').addEventListener('click', () => {
    showToast('正在返回大厅...', 'success');
    setTimeout(() => {
        showPage('hallPage');
        
        // 重置游戏状态
        if (countdownInterval) clearInterval(countdownInterval);
        selectedTarget = null;
    }, 800);
});

// 房间卡片加入按钮
document.querySelectorAll('.room-card .btn-primary').forEach(btn => {
    btn.addEventListener('click', () => {
        showToast('正在加入房间...', 'success');
        setTimeout(() => {
            showPage('roomPage');
        }, 800);
    });
});

// 快速加入按钮
document.querySelectorAll('.hall-right .btn-secondary')[0].addEventListener('click', () => {
    showToast('正在匹配房间...', 'success');
    setTimeout(() => {
        showPage('roomPage');
    }, 1200);
});

// 房间号加入
document.querySelector('.input-group .btn-primary').addEventListener('click', () => {
    const input = document.querySelector('.input-group .input');
    if (input.value.trim()) {
        showToast(`正在加入房间 ${input.value}...`, 'success');
        setTimeout(() => {
            showPage('roomPage');
        }, 800);
    } else {
        showToast('请输入房间号', 'error');
    }
});

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    showToast('欢迎来到AI狼人杀！', 'success');
});
