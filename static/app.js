const tg = window.Telegram.WebApp;

tg.expand();

tg.ready();


// ============ НАСТРОЙКИ ДОСТАВКИ ============

const FREE_DELIVERY_FROM = 5000;

const DELIVERY_FEE = 200;

// Слоты времени доставки (1-часовые, с 10:00 до 23:00).

// После 23:00 до 10:00 — доставка закрыта.

const DELIVERY_OPEN_HOUR = 10;

const DELIVERY_CLOSE_HOUR = 23; // до 23:00 включительно


// ============ КОРПУСА ============

const BUILDINGS_FALLBACK = [

    { id: 1, name: "Негізгі корпус", min_apt: 1, max_apt: 49 },

    { id: 2, name: "корпус 1", min_apt: 1, max_apt: 28 },

    { id: 3, name: "корпус 2", min_apt: 1, max_apt: 28 },

    { id: 4, name: "корпус 3", min_apt: 1, max_apt: 28 },

    { id: 5, name: "корпус 4", min_apt: 1, max_apt: 24 },

    { id: 6, name: "корпус 5", min_apt: 1, max_apt: 24 },

    { id: 7, name: "корпус 6", min_apt: 1, max_apt: 24 },

    { id: 8, name: "корпус 7", min_apt: 1, max_apt: 24 },

    { id: 9, name: "корпус 8", min_apt: 1, max_apt: 24 },

    { id: 10, name: "корпус 9", min_apt: 1, max_apt: 28 },

    { id: 11, name: "корпус 10", min_apt: 1, max_apt: 28 },

    { id: 12, name: "корпус 11", min_apt: 1, max_apt: 28 },

    { id: 13, name: "корпус 12", min_apt: 1, max_apt: 49 }

];

const COMPLEX_NAME = "«ҚАЙРАТ» ықшам ауданы, 135/4";


// Глобальное состояние

const state = {

    currentScreen: 'main',

    categories: [],

    productsCache: {},

    cart: {},

    currentCatId: null,

    currentPage: 1,

    hasMore: true,

    isLoading: false,

    buildings: BUILDINGS_FALLBACK,

    selectedAddress: null,

    addressFlow: { step: 'idle', buildingId: null, buildingName: null, floor: null, apt: null },

    lastOrder: null,    // детали последнего оформленного заказа

    kaspiPhone: '+7 700 000 00 00',  // фолбэк, перезаписывается из /api/me

    kaspiHolder: 'Иван Иванов'

};


// ==================== HTTP ====================

async function apiCall(endpoint, method = 'GET', body = null) {

    const initData = window.Telegram?.WebApp?.initData || "";

    const headers = {

        'Authorization': `tma ${initData}`,

        'Content-Type': 'application/json',

        'ngrok-skip-browser-warning': 'true'

    };

    const options = { method, headers };

    if (body) options.body = JSON.stringify(body);

    try {

        const response = await fetch(endpoint, options);

        if (!response.ok) {

            console.error(`API Error ${response.status} at ${endpoint}`);

            return null;

        }

        return await response.json();

    } catch (e) {

        console.error(`Network Error at ${endpoint}:`, e);

        return null;

    }

}


// ==================== НАВИГАЦИЯ ====================

function showScreen(screenId) {

    document.querySelectorAll('.screen').forEach(s => {

        s.classList.remove('active');

        s.classList.remove('hidden');

    });

    const target = document.getElementById(`screen-${screenId}`);

    if (target) target.classList.add('active');

    state.currentScreen = screenId;

    window.scrollTo({ top: 0, behavior: 'smooth' });

    if (screenId === 'cart') renderCartScreen();

    if (screenId === 'orders') loadOrders();

    // Переинициализируем маску телефона при показе корзины (на случай возврата)

    if (screenId === 'cart') initPhoneMask();

}


// ==================== КАТАЛОГ ====================

async function loadCategories() {

    const grid = document.getElementById('categories-grid');

    if (!grid) return;

    grid.innerHTML = '<div class="category-card skeleton" style="height:110px"></div>'.repeat(4);

    const data = await apiCall('/api/categories');

    if (!data || !Array.isArray(data) || data.length === 0) {

        grid.innerHTML = '<div class="empty-state"><div class="empty-icon">🛒</div><p>Витрина пуста</p></div>';

        return;

    }

    state.categories = data;

    grid.innerHTML = '';

    data.forEach(cat => {

        const el = document.createElement('div');

        el.className = 'category-card';

        const cnt = cat.products_count || 0;

        el.innerHTML = `

            <div class="category-emoji">${cat.emoji || '📦'}</div>

            <div class="category-name">${escapeHtml(cat.name)}</div>

            <div class="category-count">${cnt} ${cnt === 1 ? 'товар' : (cnt < 5 ? 'товара' : 'товаров')}</div>`;

        el.addEventListener('click', () => openCategoryPage(cat.id, cat.name));

        grid.appendChild(el);

    });

}


async function openCategoryPage(catId, catName) {

    state.currentCatId = catId;

    state.currentPage = 1;

    state.hasMore = true;

    const titleEl = document.getElementById('category-page-title');

    if (titleEl) titleEl.textContent = catName;

    const grid = document.getElementById('products-grid');

    if (grid) grid.innerHTML = '';

    const loadMoreBtn = document.getElementById('btn-load-more');

    if (loadMoreBtn) loadMoreBtn.classList.add('hidden');

    showScreen('products');

    await fetchProductsChunk();

}


async function fetchProductsChunk() {

    if (!state.hasMore || state.isLoading) return;

    state.isLoading = true;

    const grid = document.getElementById('products-grid');

    const loadMoreBtn = document.getElementById('btn-load-more');

    const emptyEl = document.getElementById('products-empty-state');

    if (loadMoreBtn) loadMoreBtn.classList.add('hidden');

    if (emptyEl) emptyEl.classList.add('hidden');

    if (!grid) { state.isLoading = false; return; }


    grid.innerHTML = '<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:12px">' +

        '<div class="product-card skeleton" style="height:200px"></div>'.repeat(4) + '</div>';


    const products = await apiCall(`/api/categories/${state.currentCatId}/products?page=${state.currentPage}`);

    grid.innerHTML = '';

    if (!products || products.length === 0) {

        if (emptyEl) {

            emptyEl.classList.remove('hidden');

            emptyEl.innerHTML = '<div class="empty-icon">📦</div><p>В этой категории пока нет товаров</p>';

        }

    } else {

        products.forEach(p => {

            state.productsCache[p.id] = p;

            renderSingleProduct(p, grid);

        });

        state.currentPage++;

        if (loadMoreBtn) loadMoreBtn.classList.toggle('hidden', products.length < 20);

    }

    state.isLoading = false;

}


function renderSingleProduct(product, container) {

    const isStopped = product.is_stopped === true;

    const card = document.createElement('div');

    card.className = 'product-card' + (isStopped ? ' product-stopped' : '');

    card.dataset.productId = product.id;

    card.innerHTML = `

        <div class="product-img-box">

            ${product.image_url

                ? `<img src="${escapeAttr(product.image_url)}" alt="${escapeAttr(product.name)}">`

                : '<span style="font-size:40px">📦</span>'}

            ${isStopped ? '<div class="stopped-overlay"><span>🚫 Стоп-лист</span></div>' : ''}

        </div>

        <div class="product-name">${escapeHtml(product.name)}</div>

        ${product.description ? `<div class="product-description">${escapeHtml(product.description)}</div>` : ''}

        <div class="product-price${isStopped ? ' product-price-stopped' : ''}">${formatMoney(product.price)}</div>

        <div id="action-slot-${product.id}">

            ${isStopped

                ? '<button class="btn-buy btn-buy-disabled" disabled>Временно недоступен</button>'

                : `<button class="btn-buy" onclick="updateCart(${product.id}, 1)">В корзину</button>`}

        </div>`;

    container.appendChild(card);

}


// ==================== КОРЗИНА ====================

function updateCart(productId, delta) {

    const cur = state.cart[productId] || 0;

    const next = cur + delta;

    if (next <= 0) delete state.cart[productId];

    else state.cart[productId] = next;

    if (tg.HapticFeedback) tg.HapticFeedback.selectionChanged();

    updateProductCardSlot(productId);

    updateCartBadge();

    if (state.currentScreen === 'cart') renderCartScreen();

}


function updateProductCardSlot(pid) {

    const slot = document.getElementById(`action-slot-${pid}`);

    if (!slot) return;

    const qty = state.cart[pid] || 0;

    if (qty === 0) {

        slot.innerHTML = `<button class="btn-buy" onclick="updateCart(${pid}, 1)">В корзину</button>`;

    } else {

        slot.innerHTML = `<div class="qty-controls">

            <button class="btn-qty" onclick="updateCart(${pid}, -1)">–</button>

            <span class="qty-val">${qty}</span>

            <button class="btn-qty" onclick="updateCart(${pid}, 1)">+</button>

        </div>`;

    }

}


function updateCartBadge() {

    const total = Object.values(state.cart).reduce((a, b) => a + b, 0);

    const badge = document.getElementById('cart-badge');

    if (!badge) return;

    if (total > 0) { badge.textContent = total; badge.classList.remove('hidden'); }

    else badge.classList.add('hidden');

}


function renderCartScreen() {

    const emptyEl = document.getElementById('cart-empty-state');

    const formEl = document.getElementById('cart-checkout-form');

    const clearBtn = document.getElementById('btn-clear-cart');

    const listEl = document.getElementById('cart-items-list');

    const ids = Object.keys(state.cart);

    if (ids.length === 0) {

        if (emptyEl) emptyEl.classList.remove('hidden');

        if (formEl) formEl.classList.add('hidden');

        if (clearBtn) clearBtn.classList.add('hidden');

        return;

    }

    if (emptyEl) emptyEl.classList.add('hidden');

    if (formEl) formEl.classList.remove('hidden');

    if (clearBtn) clearBtn.classList.remove('hidden');

    listEl.innerHTML = '';

    let sum = 0;

    ids.forEach(pid => {

        const item = state.productsCache[pid];

        const qty = state.cart[pid];

        if (!item) return;

        sum += item.price * qty;

        const row = document.createElement('div');

        row.className = 'cart-row';

        row.innerHTML = `<div class="cart-row-info">

            <div class="cart-row-title">${escapeHtml(item.name)}</div>

            <div class="cart-row-price">${formatMoney(item.price)} × ${qty}</div>

        </div>

        <div style="width:100px"><div class="qty-controls">

            <button class="btn-qty" onclick="updateCart(${pid}, -1)">–</button>

            <span class="qty-val">${qty}</span>

            <button class="btn-qty" onclick="updateCart(${pid}, 1)">+</button>

        </div></div>`;

        listEl.appendChild(row);

    });

    const fee = sum >= FREE_DELIVERY_FROM ? 0 : DELIVERY_FEE;

    document.getElementById('summary-subtotal').textContent = formatMoney(sum);

    document.getElementById('summary-delivery').textContent = fee === 0 ? 'Бесплатно' : formatMoney(fee);

    document.getElementById('summary-grand-total').textContent = formatMoney(sum + fee);

    renderDeliveryTimeOptions();

    renderKaspiInfo();

}


// Показываем реквизиты Kaspi если выбран этот способ оплаты

function renderKaspiInfo() {

    const box = document.getElementById('kaspi-payment-info');

    if (!box) return;

    const selected = document.querySelector('input[name="payment_method"]:checked')?.value;

    if (selected === 'kaspi') {

        box.innerHTML = `

            <div class="kaspi-card">

                <div class="kaspi-card-title">Переведите на Kaspi:</div>

                <div class="kaspi-row"><span>📱 Телефон</span><b><code>${escapeHtml(state.kaspiPhone)}</code></b></div>

                <div class="kaspi-row"><span>👤 Получатель</span><b>${escapeHtml(state.kaspiHolder)}</b></div>

                <div class="kaspi-hint">В комментарии к переводу укажите номер заказа.</div>

            </div>`;

        box.classList.remove('hidden');

    } else {

        box.innerHTML = '';

        box.classList.add('hidden');

    }

}


// Делегируем обработку смены способа оплаты

document.addEventListener('change', (e) => {

    if (e.target && e.target.name === 'payment_method') renderKaspiInfo();

});


// ==================== ВРЕМЯ ДОСТАВКИ ====================

// Возвращает true если сейчас можно принимать заказы (с 10:00 до 23:00)

function isDeliveryOpen() {

    const h = new Date().getHours();

    return h >= DELIVERY_OPEN_HOUR && h < DELIVERY_CLOSE_HOUR;

}


// Строит список опций времени: "Как можно скорее" + слоты с 10 до 23

function renderDeliveryTimeOptions() {

    const select = document.getElementById('checkout-time');

    if (!select) return;

    const wasValue = select.value;

    select.innerHTML = '';


    if (!isDeliveryOpen()) {

        // Доставка закрыта — показываем слоты на завтра с 10:00

        const opt = document.createElement('option');

        opt.value = '';

        opt.textContent = `Доставка закрыта (открываемся в ${DELIVERY_OPEN_HOUR}:00)`;

        opt.disabled = true;

        opt.selected = true;

        select.appendChild(opt);

        select.disabled = true;

        const hint = document.getElementById('delivery-closed-hint');

        if (hint) hint.classList.remove('hidden');

        return;

    }


    select.disabled = false;

    const hint = document.getElementById('delivery-closed-hint');

    if (hint) hint.classList.add('hidden');


    const asap = document.createElement('option');

    asap.value = 'Как можно скорее (15-20 мин)';

    asap.textContent = '⚡ Как можно скорее (15-20 мин)';

    select.appendChild(asap);


    const now = new Date();

    const currentHour = now.getHours();

    const currentMin = now.getMinutes();


    for (let h = DELIVERY_OPEN_HOUR; h < DELIVERY_CLOSE_HOUR; h++) {

        const slotStart = `${String(h).padStart(2, '0')}:00`;

        const slotEnd = `${String(h + 1).padStart(2, '0')}:00`;

        const slotValue = `${slotStart}-${slotEnd}`;

        const slotLabel = `${slotStart}–${slotEnd}`;

        // Пропускаем слоты которые уже невозможны (прошло меньше 30 минут до начала)

        if (h < currentHour || (h === currentHour && currentMin >= 30)) continue;

        const opt = document.createElement('option');

        opt.value = slotValue;

        opt.textContent = `🕐 ${slotLabel}`;

        select.appendChild(opt);

    }


    // Восстанавливаем значение если возможно

    if (wasValue && Array.from(select.options).some(o => o.value === wasValue)) {

        select.value = wasValue;

    }

}


// ==================== МАСКА ТЕЛЕФОНА +7 (XXX) XXX-XX-XX ====================

function initPhoneMask() {

    const input = document.getElementById('checkout-phone');

    if (!input || input.dataset.masked === '1') return;

    input.dataset.masked = '1';


    // Фиксируем +7 как префикс

    input.value = '+7 ';

    input.setSelectionRange(3, 3);


    input.addEventListener('focus', () => {

        if (!input.value.startsWith('+7 ')) {

            input.value = '+7 ' + input.value.replace(/^\+7\s*/, '').replace(/\D/g, '');

            applyMask(input);

        }

        if (input.selectionStart < 3) input.setSelectionRange(3, 3);

    });


    input.addEventListener('click', () => {

        if (input.selectionStart < 3) input.setSelectionRange(3, 3);

    });


    input.addEventListener('keydown', (e) => {

        // Запрещаем удаление +7

        if ((e.key === 'Backspace' || e.key === 'Delete') && input.selectionStart <= 3) {

            e.preventDefault();

        }

    });


    input.addEventListener('input', () => applyMask(input));

}


function applyMask(input) {

    // Берём только цифры после +7

    const digits = input.value.replace(/\D/g, '').replace(/^7/, '');

    let cursorPos = input.selectionStart;

    const oldLength = input.value.length;


    let formatted = '+7 ';

    if (digits.length > 0) formatted += '(' + digits.substring(0, 3);

    if (digits.length >= 3) formatted += ') ';

    if (digits.length >= 3) formatted += digits.substring(3, 6);

    if (digits.length >= 6) formatted += '-' + digits.substring(6, 8);

    if (digits.length >= 8) formatted += '-' + digits.substring(8, 10);


    input.value = formatted;

    // Грубая коррекция курсора: пытаемся сохранить примерную позицию

    const newLength = input.value.length;

    const delta = newLength - oldLength;

    let newCursor = cursorPos + delta;

    if (newCursor < 3) newCursor = 3;

    if (newCursor > newLength) newCursor = newLength;

    input.setSelectionRange(newCursor, newCursor);

}


// Возвращает чистый номер (+7XXXXXXXXXX) или пустую строку

function getPhoneDigits(input) {

    if (!input) return '';

    const digits = input.value.replace(/\D/g, '');

    if (digits.startsWith('7')) return '+' + digits;

    if (digits.length > 0) return '+7' + digits;

    return '';

}


// ==================== АДРЕС (UI выбор) ====================

async function loadBuildings() {

    try {

        const data = await apiCall('/api/buildings');

        if (data && Array.isArray(data.buildings) && data.buildings.length > 0) {

            state.buildings = data.buildings;

        }

    } catch (e) { /* fallback */ }

}


async function loadKaspiInfo() {

    try {

        const me = await apiCall('/api/me');

        if (me?.kaspi_phone) state.kaspiPhone = me.kaspi_phone;

        if (me?.kaspi_holder) state.kaspiHolder = me.kaspi_holder;

    } catch (e) { /* fallback */ }

}


function openAddressFlow() {

    state.addressFlow = { step: 'building', buildingId: null, buildingName: null, floor: null, apt: null };

    renderAddressModal();

    document.getElementById('address-modal')?.classList.remove('hidden');

}


function closeAddressModal() {

    document.getElementById('address-modal')?.classList.add('hidden');

}


function renderAddressModal() {

    const modal = document.getElementById('address-modal');

    if (!modal) return;

    const flow = state.addressFlow;

    let html = '<div class="modal-sheet">';


    if (flow.step === 'building') {

        html += `<div class="modal-title">Шаг 1 из 3</div>`;

        html += `<div class="modal-hint">Выберите корпус</div>`;

        html += `<div class="buildings-grid">`;

        state.buildings.forEach(b => {

            html += `<button class="building-btn" data-action="bld" data-id="${b.id}">🏢 ${escapeHtml(b.name)}</button>`;

        });

        html += `</div>`;

    } else if (flow.step === 'floor') {

        const building = state.buildings.find(b => b.id === flow.buildingId);

        const maxFloor = getMaxFloor(building);

        html += `<div class="modal-title">Шаг 2 из 3</div>`;

        html += `<div class="modal-hint">${escapeHtml(building.name)} — выберите этаж</div>`;

        html += `<div class="floors-grid">`;

        for (let f = 1; f <= maxFloor; f++) {

            html += `<button class="floor-btn" data-action="floor" data-num="${f}">${f}</button>`;

        }

        html += `</div>`;

        html += `<button class="modal-back-btn" data-action="back-buildings">← Сменить корпус</button>`;

    } else if (flow.step === 'apartment') {

        const building = state.buildings.find(b => b.id === flow.buildingId);

        html += `<div class="modal-title">Шаг 3 из 3</div>`;

        html += `<div class="modal-hint">${escapeHtml(building.name)}, этаж ${flow.floor} — выберите квартиру</div>`;

        html += renderApartmentGrid(building, flow.floor);

        html += `<button class="modal-back-btn" data-action="back-floors">← Сменить этаж</button>`;

    } else if (flow.step === 'confirm') {

        const building = state.buildings.find(x => x.id === flow.buildingId);

        const fullAddress = `${COMPLEX_NAME}, ${building.name}, этаж ${flow.floor}, кв. ${flow.apt}`;

        html += `<div class="modal-title">Подтвердите адрес</div>`;

        html += `<div class="confirm-address">${escapeHtml(fullAddress)}</div>`;

        html += `<div class="modal-actions">

            <button class="btn-secondary" data-action="address-restart">Изменить</button>

            <button class="btn-primary" data-action="address-confirm">Подтвердить</button>

        </div>`;

    }


    html += `<button class="modal-close-btn" data-action="modal-close">✕</button>`;

    html += '</div>';

    modal.innerHTML = html;

}


function getMaxFloor(building) {

    return Math.max(1, Math.ceil((building.max_apt - building.min_apt + 1) / 4));

}


function getFloorApartmentRange(building, floor) {

    const start = (floor - 1) * 4 + 1;

    const end = Math.min(floor * 4, building.max_apt);

    return [start, end];

}


function renderApartmentGrid(building, floor) {

    const [start, end] = getFloorApartmentRange(building, floor);

    let html = `<div class="apartments-grid">`;

    for (let a = start; a <= end; a++) {

        html += `<button class="apt-btn" data-action="apt" data-num="${a}">${a}</button>`;

    }

    html += `</div>`;

    return html;

}


function updateAddressDisplay() {

    const display = document.getElementById('selected-address-display');

    const btn = document.getElementById('btn-select-address');

    const inputEl = document.getElementById('checkout-address');

    if (state.selectedAddress) {

        if (display) {

            display.innerHTML = `<div class="address-chip">📍 ${escapeHtml(state.selectedAddress)}</div>`;

            display.classList.remove('hidden');

        }

        if (btn) btn.textContent = 'Изменить адрес';

        if (inputEl) inputEl.value = state.selectedAddress;

    } else {

        if (display) { display.innerHTML = ''; display.classList.add('hidden'); }

        if (btn) btn.textContent = 'Выбрать адрес';

    }

}


// ==================== ПОДДЕРЖКА ====================

function openSupportModal() {

    document.getElementById('support-modal')?.classList.remove('hidden');

    document.getElementById('support-message')?.focus();

    updateSupportCounter();

}


function closeSupportModal() {

    document.getElementById('support-modal')?.classList.add('hidden');

    const ta = document.getElementById('support-message');

    if (ta) ta.value = '';

    updateSupportCounter();

}


function updateSupportCounter() {

    const ta = document.getElementById('support-message');

    const counter = document.getElementById('support-char-count');

    if (ta && counter) counter.textContent = `${ta.value.length} / 4000`;

}


async function sendSupportMessage() {

    const ta = document.getElementById('support-message');

    const text = (ta?.value || '').trim();

    if (!text) {

        alert('Напишите сообщение');

        return;

    }

    const btn = document.querySelector('[data-action="support-send"]');

    if (btn) { btn.disabled = true; btn.textContent = 'Отправка...'; }

    const result = await apiCall('/api/support', 'POST', { text });

    if (btn) { btn.disabled = false; btn.textContent = 'Отправить'; }

    if (result?.ok) {

        closeSupportModal();

        if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');

        tg.showAlert('✅ Сообщение отправлено! Мы ответим в Telegram.');

    } else {

        tg.showAlert('❌ Не удалось отправить. Попробуйте позже.');

    }

}


// ==================== ЧЕКАУТ ====================

async function executeCheckout(e) {

    e.preventDefault();

    if (Object.keys(state.cart).length === 0) return;


    if (!isDeliveryOpen()) {

        alert(`Сейчас доставка закрыта. Мы принимаем заказы с ${DELIVERY_OPEN_HOUR}:00 до ${DELIVERY_CLOSE_HOUR}:00.`);

        return;

    }


    // Адрес: приоритет UI-выбор, фолбэк input

    let address = state.selectedAddress;

    if (!address) {

        const inputEl = document.getElementById('checkout-address');

        if (inputEl && inputEl.value.trim() && !inputEl.value.startsWith('+7')) {

            address = inputEl.value.trim();

        }

    }

    if (!address) {

        alert('Пожалуйста, выберите адрес доставки');

        return;

    }


    const phoneInput = document.getElementById('checkout-phone');

    const phoneDigits = getPhoneDigits(phoneInput);

    if (!/^\+7\d{10}$/.test(phoneDigits)) {

        alert('Введите корректный номер телефона: +7 (XXX) XXX-XX-XX');

        phoneInput?.focus();

        return;

    }


    const timeSelect = document.getElementById('checkout-time');

    const time = timeSelect?.value;

    if (!time || timeSelect.disabled) {

        alert('Выберите время доставки');

        return;

    }


    const payment = document.querySelector('input[name="payment_method"]:checked')?.value;

    const comment = document.getElementById('checkout-comment').value.trim();

    if (!payment) {

        alert('Выберите способ оплаты');

        return;

    }


    const btn = document.getElementById('btn-submit-order');

    btn.disabled = true;

    btn.textContent = 'Отправка...';


    // Собираем детали для экрана успеха заранее

    const items = Object.keys(state.cart).map(pid => {

        const p = state.productsCache[pid];

        return p ? { id: pid, name: p.name, price: p.price, qty: state.cart[pid] } : null;

    }).filter(Boolean);

    const subtotal = items.reduce((s, i) => s + i.price * i.qty, 0);

    const fee = subtotal >= FREE_DELIVERY_FROM ? 0 : DELIVERY_FEE;


    try {

        await apiCall('/api/cart/clear', 'POST');

        for (const [pid, qty] of Object.entries(state.cart)) {

            await apiCall('/api/cart/add', 'POST', { product_id: Number(pid), quantity: qty });

        }

        const result = await apiCall('/api/checkout', 'POST', {

            address, phone: phoneDigits, delivery_time: time, payment_method: payment, comment

        });

        if (!result?.order_id) throw new Error('Нет order_id в ответе');


        // Сохраняем Kaspi-реквизиты если они пришли с бэка

        if (result.kaspi_phone) state.kaspiPhone = result.kaspi_phone;

        if (result.kaspi_holder) state.kaspiHolder = result.kaspi_holder;


        // Запоминаем детали для экрана успеха

        state.lastOrder = {

            order_id: result.order_id,

            total: subtotal + fee,

            items,

            address,

            time,

            payment,

            phone: phoneDigits

        };


        state.cart = {};

        state.selectedAddress = null;

        updateCartBadge();

        updateAddressDisplay();

        if (phoneInput) phoneInput.value = '+7 ';

        renderSuccessScreen();

        showScreen('success');

        if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');

    } catch (err) {

        console.error('Checkout error:', err);

        alert('Не удалось оформить заказ. Попробуйте ещё раз.');

        btn.disabled = false;

        btn.textContent = 'Оформить заказ';

    }

}


function renderSuccessScreen() {

    const screen = document.getElementById('screen-success');

    if (!screen || !state.lastOrder) return;

    const o = state.lastOrder;

    const itemsHtml = o.items.map(i =>

        `<div class="success-row"><span>${escapeHtml(i.name)} × ${i.qty}</span><span>${formatMoney(i.price * i.qty)}</span></div>`

    ).join('');

    const paymentLabel = o.payment === 'kaspi' ? '💳 Перевод Kaspi' : '💵 Наличные курьеру';

    let kaspiBlock = '';

    if (o.payment === 'kaspi') {

        kaspiBlock = `

            <div class="kaspi-card">

                <div class="kaspi-card-title">💳 Оплатите через Kaspi:</div>

                <div class="kaspi-row"><span>📱 Телефон</span><b><code>${escapeHtml(state.kaspiPhone)}</code></b></div>

                <div class="kaspi-row"><span>👤 Получатель</span><b>${escapeHtml(state.kaspiHolder)}</b></div>

                <div class="kaspi-row kaspi-total-row"><span>💰 Сумма</span><b>${formatMoney(o.total)}</b></div>

                <div class="kaspi-hint">В комментарии к переводу укажите: <b>Заказ #${o.order_id}</b></div>

                <div class="kaspi-hint">⏳ Подтверждение занимает до 5 минут — мы напишем вам в Telegram.</div>

            </div>`;

    }

    screen.innerHTML = `

        <div class="success-container">

            <div class="success-icon">🎉</div>

            <h2>Заказ принят!</h2>

            <p style="color: var(--hint-color); margin-bottom: 16px">Номер заказа: <b id="success-order-id">#${o.order_id}</b></p>

            <div class="success-details">

                <div class="success-row"><span>📍 Адрес</span><span style="text-align:right;max-width:60%">${escapeHtml(o.address)}</span></div>

                <div class="success-row"><span>🕐 Время</span><span>${escapeHtml(o.time)}</span></div>

                <div class="success-row"><span>💳 Оплата</span><span>${paymentLabel}</span></div>

                <div class="success-divider"></div>

                <div class="success-row success-items-title"><span>📦 Товары:</span><span></span></div>

                ${itemsHtml}

                <div class="success-divider"></div>

                <div class="success-row success-total"><span>Итого</span><span>${formatMoney(o.total)}</span></div>

            </div>

            ${kaspiBlock}

            <p class="success-hint">Курьер уже собирает пакет. Статус заказа можно отслеживать в разделе «Мои заказы».</p>

            <button id="btn-success-close" class="btn-primary">Отлично</button>

        </div>

    `;

    document.getElementById('btn-success-close')?.addEventListener('click', () => tg.close());

}


// ==================== ИСТОРИЯ ====================

async function loadOrders() {

    const list = document.getElementById('orders-history-list');

    if (!list) {

        console.error('orders-history-list not found');

        return;

    }

    list.innerHTML = '<p style="text-align:center;padding:20px">Загрузка...</p>';

    try {

        const orders = await apiCall('/api/orders');

        if (!orders || orders.length === 0) {

            list.innerHTML = '<p class="empty-state">У вас ещё нет заказов</p>';

            return;

        }

        list.innerHTML = '';

        orders.forEach(o => {

            try {

                const d = o.created_at ? new Date(o.created_at).toLocaleDateString('ru-RU', {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '';

                const el = document.createElement('div');

                el.className = 'order-card';

                el.innerHTML = `<div class="order-header">

                    <span>Заказ #${o.id}</span>

                    <span class="order-status ${escapeAttr(o.status || '')}">${escapeHtml(o.status_label || o.status || '')}</span>

                </div>

                <div style="font-size:13px;color:var(--hint-color);margin-bottom:6px">${escapeHtml(o.address || '')}</div>

                <div style="display:flex;justify-content:space-between;font-size:14px;font-weight:600">

                    <span>${d}</span><span>${formatMoney(o.total)}</span>

                </div>`;

                list.appendChild(el);

            } catch (cardErr) {

                console.error('Order card render error:', cardErr, o);

            }

        });

    } catch (err) {

        console.error('loadOrders failed:', err);

        list.innerHTML = `<p style="color:red;text-align:center;padding:20px">Ошибка загрузки: ${escapeHtml(err.message)}</p>`;

    }

}


// ==================== ХЕЛПЕРЫ ====================

function formatMoney(amount) {

    return `${Math.round(Number(amount) || 0).toLocaleString('ru-RU')} ₸`;

}

function escapeHtml(s) {

    if (s == null) return '';

    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));

}

function escapeAttr(s) { return escapeHtml(s); }


// ==================== ДЕЛЕГИРОВАННЫЙ ОБРАБОТЧИК КЛИКОВ ====================

document.addEventListener('click', (e) => {

    const btn = e.target.closest('[data-action]');

    if (!btn) return;

    const action = btn.dataset.action;

    const flow = state.addressFlow;


    if (action === 'bld') {

        const id = parseInt(btn.dataset.id);

        const b = state.buildings.find(x => x.id === id);

        flow.buildingId = id;

        flow.buildingName = b.name;

        flow.step = 'floor';

        renderAddressModal();

    } else if (action === 'floor') {

        flow.floor = parseInt(btn.dataset.num);

        flow.step = 'apartment';

        renderAddressModal();

    } else if (action === 'apt') {

        flow.apt = parseInt(btn.dataset.num);

        flow.step = 'confirm';

        renderAddressModal();

    } else if (action === 'back-buildings') {

        flow.step = 'building'; flow.buildingId = null; flow.buildingName = null;

        renderAddressModal();

    } else if (action === 'back-floors') {

        flow.step = 'floor'; flow.floor = null;

        renderAddressModal();

    } else if (action === 'address-restart') {

        flow.step = 'building'; flow.buildingId = null; flow.buildingName = null; flow.floor = null; flow.apt = null;

        renderAddressModal();

    } else if (action === 'address-confirm') {

        const building = state.buildings.find(x => x.id === flow.buildingId);

        state.selectedAddress = `${COMPLEX_NAME}, ${building.name}, этаж ${flow.floor}, кв. ${flow.apt}`;

        closeAddressModal();

        updateAddressDisplay();

        if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');

    } else if (action === 'modal-close') {

        closeAddressModal();

    } else if (action === 'support-close') {

        closeSupportModal();

    } else if (action === 'support-send') {

        sendSupportMessage();

    }

});


// ==================== СТАРТ ====================

document.addEventListener('DOMContentLoaded', () => {

    const userName = tg.initDataUnsafe?.user?.first_name || 'Сосед';

    const greetEl = document.getElementById('user-greeting-text');

    if (greetEl) greetEl.textContent = `Привет, ${userName}!`;


    document.querySelectorAll('.bottom-nav .nav-item').forEach(btn => {

        btn.addEventListener('click', () => {

            if (btn.id === 'nav-support-btn') {

                openSupportModal();

                return;

            }

            showScreen(btn.dataset.target);

        });

    });


    const back = document.getElementById('btn-back-to-cats');

    if (back) back.addEventListener('click', () => showScreen('main'));

    const more = document.getElementById('btn-load-more');

    if (more) more.addEventListener('click', fetchProductsChunk);

    document.querySelectorAll('.go-to-catalog-btn').forEach(b => b.addEventListener('click', () => showScreen('main')));


    const clear = document.getElementById('btn-clear-cart');

    if (clear) clear.addEventListener('click', () => {

        state.cart = {}; state.selectedAddress = null;

        updateCartBadge(); updateAddressDisplay(); renderCartScreen();

    });


    const form = document.getElementById('cart-checkout-form');

    if (form) form.addEventListener('submit', executeCheckout);

    const succ = document.getElementById('btn-success-close');

    if (succ) succ.addEventListener('click', () => tg.close());


    const addrBtn = document.getElementById('btn-select-address');

    if (addrBtn) addrBtn.addEventListener('click', openAddressFlow);


    const supportTa = document.getElementById('support-message');

    if (supportTa) supportTa.addEventListener('input', updateSupportCounter);


    initPhoneMask();

    loadBuildings();

    loadKaspiInfo();

    loadCategories();

});