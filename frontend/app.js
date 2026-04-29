// === Configuracion ===
const SUPABASE_URL = "https://gsjlkppgsyjoddihuuup.supabase.co";
const SUPABASE_ANON_KEY = "sb_publishable_ECw9E40Z7N5FbQ54LP9kgQ_mOMz_289";
const supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

const API_URL = window.location.hostname === "localhost"
    ? "http://localhost:8000"
    : "https://tiqueteras-app.onrender.com";

var usuarioActualId = null;
var usuarioActualNombre = "";
var usuarioActualTipo = "recurrente";
var diasGlobales = [];

// === Multi-sede ===
var miPerfil = null;
var sedeActual = null;
var verInactivos = false;
var offsetDias = 0;

// === Finanzas y ordenamiento ===
var precioTicket = 0;
var sortMode = "nombre";
var ultimosDatosDashboard = null;

// === Toasts ===

function mostrarToast(mensaje, tipo) {
    tipo = tipo || "info";
    var container = document.getElementById("toastContainer");
    var colores = {
        success: "bg-green-600",
        error: "bg-red-600",
        info: "bg-brand-600"
    };
    var iconos = {
        success: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>',
        error: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>',
        info: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>'
    };

    var toast = document.createElement("div");
    toast.className = "toast-enter pointer-events-auto flex items-center gap-2 px-4 py-3 rounded-xl shadow-lg text-white text-sm " + (colores[tipo] || colores.info);
    toast.innerHTML = '<svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">' + (iconos[tipo] || iconos.info) + '</svg>' + escaparHtml(mensaje);
    container.appendChild(toast);

    setTimeout(function() {
        toast.classList.remove("toast-enter");
        toast.classList.add("toast-exit");
        setTimeout(function() { toast.remove(); }, 300);
    }, 3000);
}

// === Indicador de carga ===

function mostrarCarga(msg) {
    var el = document.getElementById("loadingOverlay");
    if (el) {
        document.getElementById("loadingMsg").textContent = msg || "Conectando con el servidor...";
        el.classList.remove("hidden");
    }
    document.getElementById("tableContainer").classList.add("hidden");
    document.getElementById("emptyState").classList.add("hidden");
}

function ocultarCarga() {
    var el = document.getElementById("loadingOverlay");
    if (el) el.classList.add("hidden");
}

// === Autenticacion ===

async function obtenerToken() {
    var result = await supabaseClient.auth.getSession();
    var session = result.data.session;
    if (!session) {
        window.location.href = "login.html";
        return null;
    }
    return session.access_token;
}

function authHeaders(token) {
    return { "Content-Type": "application/json", "Authorization": "Bearer " + token };
}

async function cerrarSesion() {
    await supabaseClient.auth.signOut();
    window.location.href = "login.html";
}

// Verificar sesion al cargar
supabaseClient.auth.getSession().then(function(result) {
    if (!result.data.session) {
        window.location.href = "login.html";
    } else {
        cargarPerfil();
    }
});

// === Fetch con reintentos ===

async function fetchConReintentos(url, opciones, maxIntentos) {
    maxIntentos = maxIntentos || 3;
    for (var intento = 1; intento <= maxIntentos; intento++) {
        try {
            var res = await fetch(url, opciones);
            if (res.status === 401) {
                await cerrarSesion();
                return null;
            }
            if (res.status === 403 || res.status === 400) {
                return res;
            }
            if (!res.ok) throw new Error("HTTP " + res.status);
            return res;
        } catch (err) {
            if (intento < maxIntentos) {
                mostrarCarga("Reintentando conexion... (" + intento + "/" + maxIntentos + ")");
                await new Promise(function(r) { setTimeout(r, 3000 * intento); });
            } else {
                ocultarCarga();
                mostrarToast("Error de conexion con el servidor", "error");
                return null;
            }
        }
    }
    return null;
}

// === Utilidades ===

function escaparHtml(texto) {
    var div = document.createElement("div");
    div.textContent = texto;
    return div.innerHTML;
}

function inicialDia(fechaStr) {
    var dateObj = new Date(fechaStr + "T00:00:00");
    return ["D", "L", "M", "Mi", "J", "V", "S"][dateObj.getDay()];
}

function nombreDiaCorto(fechaStr) {
    return new Date(fechaStr + "T00:00:00").toLocaleDateString("es-CO", { weekday: "short" });
}

function formatearFechaCorta(fechaStr) {
    var parts = fechaStr.split("-");
    return parts[2] + "/" + parts[1];
}

function formatearFechaCompleta(fechaStr) {
    if (!fechaStr || fechaStr === "Sin saldo" || fechaStr === "En deuda" || fechaStr.indexOf("Suficiente") !== -1) {
        return fechaStr;
    }
    var parts = fechaStr.split("-");
    var dateObj = new Date(parts[0], parts[1] - 1, parts[2]);
    return dateObj.toLocaleDateString("es-CO", { weekday: "long", year: "numeric", month: "long", day: "numeric" });
}

// === Perfil y sede ===

async function cargarPerfil() {
    var token = await obtenerToken();
    if (!token) return;

    mostrarCarga("Verificando permisos...");

    var res = await fetchConReintentos(
        API_URL + "/mi-perfil",
        { headers: { "Authorization": "Bearer " + token } }
    );

    if (!res) return;

    if (res.status === 403) {
        ocultarCarga();
        document.getElementById("mainContent").classList.add("hidden");
        document.getElementById("sinAcceso").classList.remove("hidden");
        return;
    }

    miPerfil = await res.json();

    if (miPerfil.rol === "superadmin") {
        sedeActual = miPerfil.sedes.length > 0 ? miPerfil.sedes[0].id : null;
    } else {
        sedeActual = miPerfil.sede_id;
    }

    actualizarUISegunPerfil();
    cargarConfiguracion();
    cargarDashboard();
}

function actualizarUISegunPerfil() {
    var sedeBadge = document.getElementById("sedeBadge");
    var sedeSelector = document.getElementById("sedeSelector");
    var btnConfig = document.getElementById("btnConfig");

    if (miPerfil.rol === "superadmin") {
        // Mostrar selector de sedes
        sedeBadge.classList.add("hidden");
        sedeSelector.classList.remove("hidden");
        btnConfig.classList.remove("hidden");

        sedeSelector.innerHTML = "";
        miPerfil.sedes.forEach(function(s) {
            if (!s.activa) return;
            var opt = document.createElement("option");
            opt.value = s.id;
            opt.textContent = s.nombre;
            if (s.id === sedeActual) opt.selected = true;
            sedeSelector.appendChild(opt);
        });
    } else {
        // Mostrar badge estatico
        sedeSelector.classList.add("hidden");
        btnConfig.classList.add("hidden");
        sedeBadge.classList.remove("hidden");
        sedeBadge.textContent = miPerfil.sede_nombre || "Sin sede";
    }
}

function cambiarSede(nuevoSedeId) {
    sedeActual = parseInt(nuevoSedeId);
    offsetDias = 0;
    cargarConfiguracion();
    cargarDashboard();
}

async function cargarConfiguracion() {
    var token = await obtenerToken();
    if (!token) return;
    var url = API_URL + "/configuracion";
    if (sedeActual) url += "?sede_id=" + sedeActual;
    var res = await fetchConReintentos(url, { headers: { "Authorization": "Bearer " + token } });
    if (!res || res.status === 403) return;
    var data = await res.json();
    precioTicket = data.precio_ticket || 0;
}

function navegarCalendario(dias) {
    if (dias === 0) {
        offsetDias = 0;
    } else {
        offsetDias += dias;
    }
    cargarDashboard();
}

function toggleVerInactivos() {
    verInactivos = !verInactivos;
    var btn = document.getElementById("btnVerInactivos");
    var txt = document.getElementById("txtVerInactivos");
    if (verInactivos) {
        btn.classList.remove("bg-white", "text-gray-700");
        btn.classList.add("bg-orange-50", "text-orange-600", "border-orange-200");
        txt.textContent = "Ocultar inactivos";
    } else {
        btn.classList.remove("bg-orange-50", "text-orange-600", "border-orange-200");
        btn.classList.add("bg-white", "text-gray-700");
        txt.textContent = "Ver inactivos";
    }
    cargarDashboard();
}

// === Recarga silenciosa (sin ocultar tabla) ===

var toastLentoTimer = null;

async function recargarSilencioso() {
    var token = await obtenerToken();
    if (!token) return;

    // Si tarda mas de 3s, mostrar toast
    toastLentoTimer = setTimeout(function() {
        mostrarToast("Procesando, el servidor esta respondiendo...", "info");
    }, 3000);

    var url = API_URL + "/dashboard?incluir_inactivos=" + (verInactivos ? 1 : 0) + "&offset_dias=" + offsetDias;
    if (sedeActual) url += "&sede_id=" + sedeActual;

    var res = await fetchConReintentos(url, { headers: { "Authorization": "Bearer " + token } });

    clearTimeout(toastLentoTimer);

    // Quitar estados de procesando
    document.querySelectorAll(".celda-procesando, .th-procesando").forEach(function(el) {
        el.classList.remove("celda-procesando", "th-procesando");
    });

    if (!res || res.status === 403) return;

    var data = await res.json();
    diasGlobales = data.dias_globales || [];
    document.getElementById("metricHoy").innerText = data.metricas.almuerzos_hoy;

    if (data.fechas_columnas && data.fechas_columnas.length > 0) {
        var primera = formatearFechaCorta(data.fechas_columnas[0]);
        var ultima = formatearFechaCorta(data.fechas_columnas[data.fechas_columnas.length - 1]);
        document.getElementById("rangoFechas").textContent = primera + " - " + ultima;
    }

    ultimosDatosDashboard = data;
    if (data.usuarios.length === 0) {
        document.getElementById("emptyState").classList.remove("hidden");
        document.getElementById("tableContainer").classList.add("hidden");
    } else {
        document.getElementById("emptyState").classList.add("hidden");
        document.getElementById("tableContainer").classList.remove("hidden");
        renderizarCalendario(data);
    }
}

// === Dashboard ===

async function cargarDashboard() {
    var token = await obtenerToken();
    if (!token) return;

    mostrarCarga("Cargando datos del servidor...");

    var url = API_URL + "/dashboard?incluir_inactivos=" + (verInactivos ? 1 : 0) + "&offset_dias=" + offsetDias;
    if (sedeActual) url += "&sede_id=" + sedeActual;

    var res = await fetchConReintentos(url, { headers: { "Authorization": "Bearer " + token } });

    ocultarCarga();
    if (!res || res.status === 403) return;

    var data = await res.json();
    diasGlobales = data.dias_globales || [];
    document.getElementById("metricHoy").innerText = data.metricas.almuerzos_hoy;

    // Actualizar rango de fechas y boton Hoy
    if (data.fechas_columnas && data.fechas_columnas.length > 0) {
        var primera = formatearFechaCorta(data.fechas_columnas[0]);
        var ultima = formatearFechaCorta(data.fechas_columnas[data.fechas_columnas.length - 1]);
        document.getElementById("rangoFechas").textContent = primera + " - " + ultima;
    }
    var btnHoy = document.getElementById("btnHoy");
    if (offsetDias !== 0) {
        btnHoy.classList.remove("hidden");
    } else {
        btnHoy.classList.add("hidden");
    }

    ultimosDatosDashboard = data;
    if (data.usuarios.length === 0) {
        document.getElementById("emptyState").classList.remove("hidden");
        document.getElementById("tableContainer").classList.add("hidden");
    } else {
        document.getElementById("emptyState").classList.add("hidden");
        document.getElementById("tableContainer").classList.remove("hidden");
        renderizarCalendario(data);
    }
}

function toggleSort() {
    sortMode = sortMode === "nombre" ? "saldo_asc" : "nombre";
    var btn = document.getElementById("btnSort");
    var txt = document.getElementById("txtSort");
    if (sortMode === "saldo_asc") {
        btn.classList.remove("bg-white", "text-gray-700", "border-gray-200");
        btn.classList.add("bg-brand-50", "text-brand-600", "border-brand-200");
        txt.textContent = "Tiquetes ↑";
    } else {
        btn.classList.remove("bg-brand-50", "text-brand-600", "border-brand-200");
        btn.classList.add("bg-white", "text-gray-700", "border-gray-200");
        txt.textContent = "A-Z";
    }
    if (ultimosDatosDashboard) {
        renderizarCalendario(ultimosDatosDashboard);
    }
}

function renderizarCalendario(data) {
    var thead = document.getElementById("calendarHead");
    var tbody = document.getElementById("calendarBody");
    var hoyStr = new Date().toISOString().split("T")[0];

    var htmlHead = '<tr><th class="p-3 w-44 sticky left-0 bg-gray-50 z-20 border-r border-gray-200">Persona</th>';
    data.fechas_columnas.forEach(function(fecha) {
        var dateObj = new Date(fecha + "T00:00:00");
        var isSunday = dateObj.getDay() === 0;
        var isToday = fecha === hoyStr;
        var isGlobal = diasGlobales.indexOf(fecha) !== -1;

        var bg = isToday ? "bg-brand-50" : isGlobal ? "bg-red-50" : "bg-gray-50";
        var text = isSunday ? "text-red-400" : "text-gray-500";
        var todayRing = isToday ? "ring-2 ring-brand-500 ring-inset" : "";

        htmlHead += '<th class="p-1.5 text-center min-w-[70px] border-l border-gray-100 cursor-pointer select-none ' + bg + " " + todayRing + '"'
            + ' onclick="toggleDiaGlobal(\'' + fecha + '\')"'
            + ' title="Click para marcar/desmarcar festivo">'
            + '<div class="capitalize text-[11px] font-medium ' + text + '">' + nombreDiaCorto(fecha) + '</div>'
            + '<div class="text-[10px] text-gray-400 mt-0.5">' + formatearFechaCorta(fecha) + '</div>'
            + (isGlobal ? '<div class="text-[8px] text-red-500 font-bold mt-0.5">FESTIVO</div>' : '')
            + '</th>';
    });
    htmlHead += '</tr>';
    thead.innerHTML = htmlHead;

    // Ordenar usuarios segun el modo activo
    var usuarios = data.usuarios.slice();
    if (sortMode === "saldo_asc") {
        usuarios.sort(function(a, b) { return a.saldo_actual - b.saldo_actual; });
    } else {
        usuarios.sort(function(a, b) { return a.nombre.localeCompare(b.nombre, "es"); });
    }

    var htmlBody = "";
    usuarios.forEach(function(user) {
        var nombreSafe = escaparHtml(user.nombre);
        var esInactivo = user.activo === 0;
        var esEsporadico = user.tipo === "esporadico";
        var esEmpresa = user.tipo === "empresa";
        var saldoColor = user.saldo_actual < 0 ? "text-red-500" : (esEmpresa ? "text-teal-600" : "text-brand-600");
        var saldoSign = user.saldo_actual < 0 ? "" : (esEmpresa ? "" : "+");
        var saldoBadge = esEmpresa ? '' : '<span class="' + saldoColor + ' text-[11px] font-semibold ml-1.5">' + saldoSign + user.saldo_actual + '</span>';
        var inactivoBadge = esInactivo ? '<span class="text-[10px] text-orange-500 bg-orange-50 px-1.5 py-0.5 rounded ml-1.5 font-medium">Inactivo</span>' : '';
        var esporadicoBadge = (!esInactivo && esEsporadico) ? '<span class="text-[10px] text-purple-500 bg-purple-50 px-1.5 py-0.5 rounded ml-1.5 font-medium">Esporadico</span>' : '';
        var empresaBadge = (!esInactivo && esEmpresa) ? '<span class="text-[10px] text-teal-600 bg-teal-50 px-1.5 py-0.5 rounded ml-1.5 font-medium">Empresa</span>' : '';
        var rowOpacity = esInactivo ? "opacity-50" : "";

        htmlBody += '<tr class="border-b border-gray-100 user-row hover:bg-gray-50/50 transition-colors ' + rowOpacity + '" data-nombre="' + nombreSafe.toLowerCase() + '">'
            + '<td class="p-2.5 font-medium cursor-pointer text-gray-700 hover:text-brand-600 sticky left-0 bg-white z-10 border-r border-gray-200 transition-colors"'
            + ' onclick="abrirModalPerfil(' + user.id + ',\'' + nombreSafe.replace(/'/g, "\\'") + '\',' + user.saldo_actual + ',\'' + escaparHtml(user.fecha_cobertura) + '\',' + user.activo + ',\'' + escaparHtml(user.email || '').replace(/'/g, "\\'") + '\',\'' + (user.tipo || 'recurrente') + '\')">'
            + '<div class="flex items-center">'
            + '<span class="truncate max-w-[120px]">' + nombreSafe + '</span>' + saldoBadge + inactivoBadge + esporadicoBadge + empresaBadge
            + '</div></td>';

        user.calendario.forEach(function(dia) {
            var inicial = inicialDia(dia.fecha);
            var todayBg = dia.es_hoy ? "bg-brand-50/50" : "";

            var colorClass = "bg-gray-100 border border-gray-200";
            var textColor = "text-gray-300";

            if (!esInactivo) {
                colorClass = "bg-white border border-gray-100";

                if (dia.estado === "past_covered") { colorClass = "bg-green-100 border border-green-200"; textColor = "text-green-400"; }
                if (dia.estado === "past_empresa") { colorClass = "bg-teal-100 border border-teal-200"; textColor = "text-teal-400"; }
                if (dia.estado === "past_fiado") { colorClass = "bg-orange-100 border border-orange-200"; textColor = "text-orange-400"; }
                if (dia.estado === "past_absence") { colorClass = "bg-gray-100 border border-gray-200"; textColor = "text-gray-400"; }
                if (dia.estado === "past_global_blocked") { colorClass = "bg-red-100 border border-red-200"; textColor = "text-red-300"; }

                if (dia.estado === "covered") { colorClass = "bg-green-500 border border-green-600"; textColor = "text-white"; }
                if (dia.estado === "empresa") { colorClass = "bg-teal-500 border border-teal-600"; textColor = "text-white"; }
                if (dia.estado === "fiado") { colorClass = "bg-orange-400 border border-orange-500"; textColor = "text-white"; }
                if (dia.estado === "sin_cobertura") { colorClass = "bg-gray-100 border border-gray-200"; textColor = "text-gray-400"; }
                if (dia.estado === "absence") { colorClass = "bg-red-500 border border-red-600"; textColor = "text-white"; }
                if (dia.estado === "sunday_blocked") { colorClass = "bg-gray-50 border border-gray-100"; textColor = "text-gray-300"; }
                if (dia.estado === "global_blocked") { colorClass = "bg-red-600 border border-red-700"; textColor = "text-white"; }
            }

            var titleText = dia.fecha + (esInactivo ? ' - Inactivo' : esEsporadico ? ' - Click para registrar/quitar asistencia' : ' - ' + dia.estado);
            htmlBody += '<td class="p-1 min-w-[70px] border-l border-gray-100 ' + todayBg + '">'
                + '<div' + (esInactivo ? '' : ' onclick="toggleExcepcion(' + user.id + ',\'' + dia.fecha + '\',event)"')
                + ' class="h-9 w-full rounded-lg ' + colorClass + (esInactivo ? '' : ' cursor-pointer hover:scale-105 hover:shadow-sm') + ' transition-all flex justify-center items-center text-xs font-medium ' + textColor + '"'
                + ' title="' + titleText + '">'
                + inicial + '</div></td>';
        });
        htmlBody += '</tr>';
    });
    tbody.innerHTML = htmlBody;
}

document.getElementById("searchInput").addEventListener("input", function(e) {
    var term = e.target.value.toLowerCase();
    document.querySelectorAll(".user-row").forEach(function(row) {
        row.style.display = row.dataset.nombre.indexOf(term) !== -1 ? "" : "none";
    });
});

// === Acciones ===

async function toggleDiaGlobal(fecha) {
    // Feedback visual en el encabezado del dia
    var ths = document.querySelectorAll("#calendarHead th");
    ths.forEach(function(th) {
        if (th.getAttribute("onclick") && th.getAttribute("onclick").indexOf(fecha) !== -1) {
            th.classList.add("th-procesando");
        }
    });

    var token = await obtenerToken();
    if (!token) return;
    var url = API_URL + "/dias-globales/";
    if (sedeActual) url += "?sede_id=" + sedeActual;
    await fetchConReintentos(url, {
        method: "POST", headers: authHeaders(token),
        body: JSON.stringify({ fecha: fecha })
    });
    recargarSilencioso();
}

async function toggleExcepcion(userId, fecha, evt) {
    // Feedback visual en la celda clickeada
    if (evt && evt.currentTarget) {
        evt.currentTarget.classList.add("celda-procesando");
    }

    var token = await obtenerToken();
    if (!token) return;
    await fetchConReintentos(API_URL + "/usuarios/" + userId + "/excepcion", {
        method: "POST", headers: authHeaders(token),
        body: JSON.stringify({ fecha: fecha })
    });
    recargarSilencioso();
}

// === Modal: Perfil ===

function abrirModalPerfil(id, nombre, saldo, cobertura, activo, email, tipo) {
    usuarioActualId = id;
    usuarioActualNombre = nombre;
    usuarioActualTipo = tipo || "recurrente";

    document.getElementById("modalNombre").innerText = nombre;

    var btnToggle = document.getElementById("btnToggleActivo");
    btnToggle.textContent = activo ? "Desactivar" : "Activar";
    btnToggle.className = activo
        ? "text-xs text-gray-400 hover:text-orange-500 transition-colors px-2 py-1 rounded hover:bg-orange-50"
        : "text-xs text-green-600 hover:text-green-700 transition-colors px-2 py-1 rounded hover:bg-green-50";

    // Switch de tipo vs badge empresa
    var switchRow = document.getElementById("tipoSwitchRow");
    var empresaRow = document.getElementById("tipoEmpresaRow");
    var switchEl = document.getElementById("switchTipo");
    if (usuarioActualTipo === "empresa") {
        switchRow.classList.add("hidden");
        empresaRow.classList.remove("hidden");
    } else {
        switchRow.classList.remove("hidden");
        empresaRow.classList.add("hidden");
        var esEsporadico = usuarioActualTipo === "esporadico";
        if (esEsporadico) {
            switchEl.classList.add("activo");
            document.getElementById("lblTipoIzq").className = "text-sm text-gray-400";
            document.getElementById("lblTipoDer").className = "text-sm font-medium text-purple-700";
        } else {
            switchEl.classList.remove("activo");
            document.getElementById("lblTipoIzq").className = "text-sm font-medium text-gray-700";
            document.getElementById("lblTipoDer").className = "text-sm text-gray-400";
        }
    }

    // Card Tiquetes
    var saldoEl = document.getElementById("modalSaldo");
    var saldoSubEl = document.getElementById("modalSaldoSub");
    var cardTiquetes = document.getElementById("cardTiquetes");
    if (saldo < 0) {
        saldoEl.className = "text-4xl font-bold mt-1 text-red-600";
        saldoEl.innerText = Math.abs(saldo);
        saldoSubEl.className = "text-[10px] mt-1.5 font-medium text-red-400";
        saldoSubEl.innerText = "en deuda";
        cardTiquetes.className = "p-4 rounded-xl border text-center transition-colors bg-red-50 border-red-200";
    } else if (saldo > 0) {
        saldoEl.className = "text-4xl font-bold mt-1 text-green-600";
        saldoEl.innerText = saldo;
        saldoSubEl.className = "text-[10px] mt-1.5 font-medium text-green-500";
        saldoSubEl.innerText = "a favor";
        cardTiquetes.className = "p-4 rounded-xl border text-center transition-colors bg-green-50 border-green-200";
    } else {
        saldoEl.className = "text-4xl font-bold mt-1 text-gray-400";
        saldoEl.innerText = "0";
        saldoSubEl.className = "text-[10px] mt-1.5 font-medium text-gray-400";
        saldoSubEl.innerText = "sin saldo";
        cardTiquetes.className = "p-4 rounded-xl border text-center transition-colors bg-gray-50 border-gray-100";
    }

    // Card COP
    var saldoCOPEl = document.getElementById("modalSaldoCOP");
    var saldoCOPSubEl = document.getElementById("modalSaldoCOPSub");
    var cardCOP = document.getElementById("cardCOP");
    if (usuarioActualTipo === "empresa") {
        saldoCOPEl.className = "text-2xl font-bold mt-1 text-teal-600";
        saldoCOPEl.textContent = "—";
        saldoCOPSubEl.textContent = "cuenta empresa";
        cardCOP.className = "p-4 rounded-xl border text-center transition-colors bg-teal-50 border-teal-200";
    } else if (precioTicket > 0) {
        var cop = Math.abs(saldo) * precioTicket;
        var copStr = "$" + cop.toLocaleString("es-CO");
        if (saldo < 0) {
            saldoCOPEl.className = "text-2xl font-bold mt-1 text-red-600";
            saldoCOPEl.textContent = copStr;
            saldoCOPSubEl.textContent = "en deuda";
            cardCOP.className = "p-4 rounded-xl border text-center transition-colors bg-red-50 border-red-200";
        } else if (saldo > 0) {
            saldoCOPEl.className = "text-2xl font-bold mt-1 text-green-600";
            saldoCOPEl.textContent = copStr;
            saldoCOPSubEl.textContent = "a favor";
            cardCOP.className = "p-4 rounded-xl border text-center transition-colors bg-green-50 border-green-200";
        } else {
            saldoCOPEl.className = "text-2xl font-bold mt-1 text-gray-400";
            saldoCOPEl.textContent = "$0";
            saldoCOPSubEl.textContent = "sin saldo";
            cardCOP.className = "p-4 rounded-xl border text-center transition-colors bg-gray-50 border-gray-100";
        }
    } else {
        saldoCOPEl.className = "text-2xl font-bold mt-1 text-gray-300";
        saldoCOPEl.textContent = "$—";
        saldoCOPSubEl.textContent = "sin precio config.";
        cardCOP.className = "p-4 rounded-xl border text-center transition-colors bg-gray-50 border-gray-100";
    }

    // Badge precio por tiquete
    var precioBadge = document.getElementById("precioTicketBadge");
    if (precioTicket > 0) {
        precioBadge.textContent = "$" + precioTicket.toLocaleString("es-CO") + " / tiquete";
        precioBadge.classList.remove("hidden");
    } else {
        precioBadge.classList.add("hidden");
    }

    document.getElementById("modalCobertura").innerText = formatearFechaCompleta(cobertura);
    document.getElementById("inputEmail").value = email || "";
    document.getElementById("inputTickets").value = "";
    document.getElementById("inputMontoPagado").value = "";
    document.getElementById("modalPerfil").classList.remove("hidden");
}

function cerrarModal() {
    document.getElementById("modalPerfil").classList.add("hidden");
    document.getElementById("inputTickets").value = "";
    document.getElementById("inputEmail").value = "";
    document.getElementById("inputMontoPagado").value = "";
}

function sincronizarDesdeMonto() {
    var monto = parseFloat(document.getElementById("inputMontoPagado").value) || 0;
    var inputTickets = document.getElementById("inputTickets");
    if (precioTicket > 0 && monto > 0 && monto % precioTicket === 0) {
        inputTickets.value = monto / precioTicket;
    } else {
        inputTickets.value = "";
    }
}

function sincronizarDesdeTickets() {
    var raw = document.getElementById("inputTickets").value;
    var tickets = parseInt(raw) || 0;
    // Forzar entero
    if (raw !== "" && String(tickets) !== raw.replace(/\..*/, "")) {
        document.getElementById("inputTickets").value = tickets || "";
    }
    var inputMonto = document.getElementById("inputMontoPagado");
    if (precioTicket > 0 && tickets > 0) {
        inputMonto.value = tickets * precioTicket;
    } else {
        inputMonto.value = "";
    }
}

async function guardarEmail() {
    var email = document.getElementById("inputEmail").value.trim();
    var token = await obtenerToken();
    if (!token) return;
    var res = await fetchConReintentos(API_URL + "/usuarios/" + usuarioActualId + "/email", {
        method: "PUT", headers: authHeaders(token),
        body: JSON.stringify({ email: email || null })
    });
    if (!res) return;
    mostrarToast(email ? "Correo guardado" : "Correo eliminado", "success");
    recargarSilencioso();
}

async function ajustarTickets(accion) {
    var tickets = parseInt(document.getElementById("inputTickets").value) || 0;
    var monto = parseFloat(document.getElementById("inputMontoPagado").value) || 0;

    if (tickets <= 0) {
        mostrarToast("Ingresa una cantidad de tiquetes mayor a 0", "error");
        return;
    }

    var token = await obtenerToken();
    if (!token) return;

    var cantidad = accion === "quitar" ? -tickets : tickets;
    var body = { cantidad: cantidad };
    if (precioTicket > 0) body.precio_snapshot = precioTicket;
    if (monto > 0 && accion === "agregar") body.monto_pagado = monto;

    var res = await fetchConReintentos(API_URL + "/usuarios/" + usuarioActualId + "/tickets", {
        method: "POST", headers: authHeaders(token),
        body: JSON.stringify(body)
    });
    if (!res) return;
    cerrarModal();
    mostrarToast(accion === "agregar" ? "Tickets abonados correctamente" : "Tickets removidos correctamente", "success");
    recargarSilencioso();
}

async function toggleActivoUsuario() {
    var token = await obtenerToken();
    if (!token) return;
    var res = await fetchConReintentos(API_URL + "/usuarios/" + usuarioActualId + "/toggle-activo", {
        method: "PUT", headers: { "Authorization": "Bearer " + token }
    });
    if (!res) return;
    var data = await res.json();
    cerrarModal();
    mostrarToast(usuarioActualNombre + (data.activo ? " activado" : " desactivado"), "success");
    recargarSilencioso();
}

async function cambiarTipoUsuario() {
    if (usuarioActualTipo === "empresa") return;
    var nuevoTipo = usuarioActualTipo === "recurrente" ? "esporadico" : "recurrente";
    var token = await obtenerToken();
    if (!token) return;
    var res = await fetchConReintentos(API_URL + "/usuarios/" + usuarioActualId + "/tipo", {
        method: "PUT", headers: authHeaders(token),
        body: JSON.stringify({ tipo: nuevoTipo })
    });
    if (!res) return;
    usuarioActualTipo = nuevoTipo;
    var esEsporadico = nuevoTipo === "esporadico";
    var switchEl = document.getElementById("switchTipo");
    if (esEsporadico) {
        switchEl.classList.add("activo");
        document.getElementById("lblTipoIzq").className = "text-sm text-gray-400";
        document.getElementById("lblTipoDer").className = "text-sm font-medium text-purple-700";
    } else {
        switchEl.classList.remove("activo");
        document.getElementById("lblTipoIzq").className = "text-sm font-medium text-gray-700";
        document.getElementById("lblTipoDer").className = "text-sm text-gray-400";
    }
    mostrarToast(usuarioActualNombre + " cambiado a " + nuevoTipo, "success");
    recargarSilencioso();
}

async function eliminarUsuario() {
    if (!confirm('Eliminar a "' + usuarioActualNombre + '"? Esta accion no se puede deshacer.')) return;
    var token = await obtenerToken();
    if (!token) return;
    await fetchConReintentos(API_URL + "/usuarios/" + usuarioActualId, {
        method: "DELETE", headers: { "Authorization": "Bearer " + token }
    });
    cerrarModal();
    mostrarToast(usuarioActualNombre + " eliminado", "info");
    recargarSilencioso();
}

// === Modal: Nuevo Usuario ===

function abrirModalNuevoUsuario() {
    document.getElementById("inputNuevoNombre").value = "";
    document.getElementById("modalNuevo").classList.remove("hidden");
    setTimeout(function() { document.getElementById("inputNuevoNombre").focus(); }, 100);
}

function cerrarModalNuevo() {
    document.getElementById("modalNuevo").classList.add("hidden");
    document.getElementById("selectNuevoTipo").value = "recurrente";
}

async function crearUsuario() {
    var nombre = document.getElementById("inputNuevoNombre").value.trim();
    if (!nombre) {
        mostrarToast("Escribe un nombre", "error");
        return;
    }
    var token = await obtenerToken();
    if (!token) return;
    var tipo = document.getElementById("selectNuevoTipo").value || "recurrente";
    var body = { nombre: nombre, tipo: tipo };
    if (sedeActual) body.sede_id = sedeActual;
    var res = await fetchConReintentos(API_URL + "/usuarios/", {
        method: "POST", headers: authHeaders(token),
        body: JSON.stringify(body)
    });
    if (!res) return;
    if (res.status === 400) {
        var err = await res.json();
        mostrarToast(err.detail || "Error al crear persona", "error");
        return;
    }
    cerrarModalNuevo();
    mostrarToast(nombre + " agregado correctamente", "success");
    recargarSilencioso();
}

// Enter para crear usuario en el modal
document.addEventListener("keydown", function(e) {
    if (e.key === "Enter" && !document.getElementById("modalNuevo").classList.contains("hidden")) {
        crearUsuario();
    }
});

// === Historial de auditoria ===

var historialOffset = 0;
var historialTotal = 0;
var HISTORIAL_LIMITE = 20;

async function abrirHistorial() {
    historialOffset = 0;
    document.getElementById("modalHistorial").classList.remove("hidden");
    cargarHistorial();
}

function cerrarHistorial() {
    document.getElementById("modalHistorial").classList.add("hidden");
}

async function cargarHistorial() {
    var token = await obtenerToken();
    if (!token) return;

    document.getElementById("historialLoading").classList.remove("hidden");
    document.getElementById("historialTabla").classList.add("hidden");
    document.getElementById("historialVacio").classList.add("hidden");
    document.getElementById("historialPaginacion").classList.add("hidden");

    var url = API_URL + "/auditoria?limite=" + HISTORIAL_LIMITE + "&offset=" + historialOffset;
    if (sedeActual) url += "&sede_id=" + sedeActual;

    var res = await fetchConReintentos(url, { headers: { "Authorization": "Bearer " + token } });

    document.getElementById("historialLoading").classList.add("hidden");
    if (!res) return;

    var data = await res.json();
    historialTotal = data.total;

    if (data.logs.length === 0) {
        document.getElementById("historialVacio").classList.remove("hidden");
        return;
    }

    var tbody = document.getElementById("historialBody");
    var html = "";
    data.logs.forEach(function(log) {
        var accionColor = "text-gray-600 bg-gray-100";
        if (log.accion.indexOf("Crear") !== -1 || log.accion.indexOf("Abonar") !== -1) accionColor = "text-green-700 bg-green-50";
        if (log.accion.indexOf("Eliminar") !== -1 || log.accion.indexOf("Quitar") !== -1) accionColor = "text-red-700 bg-red-50";
        if (log.accion.indexOf("festivo") !== -1 || log.accion.indexOf("Bloquear") !== -1) accionColor = "text-orange-700 bg-orange-50";
        if (log.accion.indexOf("Exportar") !== -1) accionColor = "text-blue-700 bg-blue-50";
        if (log.accion.indexOf("Ajustar") !== -1) accionColor = "text-brand-700 bg-brand-50";

        var emailCorto = log.email ? log.email.split("@")[0] : "?";

        html += '<tr class="border-b border-gray-50 hover:bg-gray-50/50">'
            + '<td class="py-2.5 pr-3 text-gray-400 text-xs whitespace-nowrap">' + escaparHtml(log.fecha) + '</td>'
            + '<td class="py-2.5 pr-3 text-gray-600 text-xs">' + escaparHtml(emailCorto) + '</td>'
            + '<td class="py-2.5 pr-3"><span class="px-2 py-0.5 rounded-md text-[11px] font-medium ' + accionColor + '">' + escaparHtml(log.accion) + '</span></td>'
            + '<td class="py-2.5 text-gray-700 text-xs">' + escaparHtml(log.detalle) + '</td>'
            + '</tr>';
    });
    tbody.innerHTML = html;
    document.getElementById("historialTabla").classList.remove("hidden");

    document.getElementById("historialPaginacion").classList.remove("hidden");
    var desde = historialOffset + 1;
    var hasta = Math.min(historialOffset + HISTORIAL_LIMITE, historialTotal);
    document.getElementById("historialInfo").textContent = desde + "-" + hasta + " de " + historialTotal;
    document.getElementById("btnHistPrev").disabled = historialOffset === 0;
    document.getElementById("btnHistNext").disabled = historialOffset + HISTORIAL_LIMITE >= historialTotal;
}

function historialPagAnterior() {
    historialOffset = Math.max(0, historialOffset - HISTORIAL_LIMITE);
    cargarHistorial();
}

function historialPagSiguiente() {
    historialOffset += HISTORIAL_LIMITE;
    cargarHistorial();
}

// === Exportar Excel ===

async function descargarExcel() {
    var token = await obtenerToken();
    if (!token) return;
    var hoy = new Date().toISOString().split("T")[0];

    mostrarToast("Generando archivo Excel...", "info");

    try {
        var url = API_URL + "/exportar?fecha=" + hoy;
        if (sedeActual) url += "&sede_id=" + sedeActual;
        var res = await fetch(url, {
            headers: { "Authorization": "Bearer " + token }
        });
        if (!res.ok) { mostrarToast("Error al exportar", "error"); return; }
        var blob = await res.blob();
        var blobUrl = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = blobUrl;
        a.download = "comensales_" + hoy + ".xlsx";
        a.click();
        URL.revokeObjectURL(blobUrl);
        mostrarToast("Archivo descargado", "success");
    } catch (err) {
        mostrarToast("Error de conexion al exportar", "error");
    }
}

// === Configuracion (superadmin) ===

function abrirConfig() {
    document.getElementById("modalConfig").classList.remove("hidden");
    configTab("sedes");
}

function cerrarConfig() {
    document.getElementById("modalConfig").classList.add("hidden");
}

function configTab(tab) {
    var tabSedes = document.getElementById("tabSedes");
    var tabAdmins = document.getElementById("tabAdmins");
    var panelSedes = document.getElementById("panelSedes");
    var panelAdmins = document.getElementById("panelAdmins");

    if (tab === "sedes") {
        tabSedes.className = tabSedes.className.replace("tab-inactive", "tab-active");
        tabAdmins.className = tabAdmins.className.replace("tab-active", "tab-inactive");
        panelSedes.classList.remove("hidden");
        panelAdmins.classList.add("hidden");
        cargarConfigSedes();
    } else {
        tabAdmins.className = tabAdmins.className.replace("tab-inactive", "tab-active");
        tabSedes.className = tabSedes.className.replace("tab-active", "tab-inactive");
        panelAdmins.classList.remove("hidden");
        panelSedes.classList.add("hidden");
        cargarConfigAdmins();
    }
}

// --- Sedes CRUD ---

async function cargarConfigSedes() {
    var token = await obtenerToken();
    if (!token) return;

    var res = await fetchConReintentos(API_URL + "/admin/sedes", { headers: { "Authorization": "Bearer " + token } });
    if (!res || res.status === 403) return;

    var sedes = await res.json();
    var tbody = document.getElementById("configSedesBody");
    var html = "";

    sedes.forEach(function(s) {
        var estadoClass = s.activa ? "text-green-700 bg-green-50" : "text-gray-400 bg-gray-100";
        var estadoText = s.activa ? "Activa" : "Inactiva";
        var btnText = s.activa ? "Desactivar" : "Activar";
        var btnClass = s.activa ? "text-red-500 hover:bg-red-50" : "text-green-600 hover:bg-green-50";

        html += '<tr class="border-b border-gray-50">'
            + '<td class="py-3 text-gray-700 font-medium">' + escaparHtml(s.nombre) + '</td>'
            + '<td class="py-3"><span class="px-2 py-0.5 rounded-md text-[11px] font-medium ' + estadoClass + '">' + estadoText + '</span></td>'
            + '<td class="py-3 text-right">'
            + '<button onclick="toggleSede(' + s.id + ',' + (s.activa ? 0 : 1) + ')" class="text-xs px-2 py-1 rounded ' + btnClass + ' transition-colors">' + btnText + '</button>'
            + '</td></tr>';
    });

    tbody.innerHTML = html;
}

async function crearSede() {
    var input = document.getElementById("inputNuevaSede");
    var nombre = input.value.trim();
    if (!nombre) {
        mostrarToast("Escribe el nombre de la sede", "error");
        return;
    }

    var token = await obtenerToken();
    if (!token) return;

    var res = await fetchConReintentos(API_URL + "/admin/sedes", {
        method: "POST", headers: authHeaders(token),
        body: JSON.stringify({ nombre: nombre })
    });

    if (!res) return;
    if (res.status === 400) {
        var err = await res.json();
        mostrarToast(err.detail || "Error al crear sede", "error");
        return;
    }

    input.value = "";
    mostrarToast("Sede creada correctamente", "success");
    cargarConfigSedes();
    // Actualizar perfil para refrescar lista de sedes en el selector
    await recargarPerfilYSelector();
}

async function toggleSede(sedeId, nuevoEstado) {
    var token = await obtenerToken();
    if (!token) return;

    await fetchConReintentos(API_URL + "/admin/sedes/" + sedeId, {
        method: "PUT", headers: authHeaders(token),
        body: JSON.stringify({ activa: nuevoEstado })
    });

    mostrarToast(nuevoEstado ? "Sede activada" : "Sede desactivada", "success");
    cargarConfigSedes();
    await recargarPerfilYSelector();
}

async function recargarPerfilYSelector() {
    var token = await obtenerToken();
    if (!token) return;
    var res = await fetchConReintentos(API_URL + "/mi-perfil", { headers: { "Authorization": "Bearer " + token } });
    if (!res || res.status === 403) return;
    miPerfil = await res.json();
    actualizarUISegunPerfil();
}

// --- Admins CRUD ---

async function cargarConfigAdmins() {
    var token = await obtenerToken();
    if (!token) return;

    var res = await fetchConReintentos(API_URL + "/admin/admins", { headers: { "Authorization": "Bearer " + token } });
    if (!res || res.status === 403) return;

    var admins = await res.json();

    // Poblar selector de sedes para el formulario de nuevo admin
    var selectSede = document.getElementById("selectAdminSede");
    selectSede.innerHTML = '<option value="">Sin sede (superadmin)</option>';
    if (miPerfil && miPerfil.sedes) {
        miPerfil.sedes.forEach(function(s) {
            var opt = document.createElement("option");
            opt.value = s.id;
            opt.textContent = s.nombre;
            selectSede.appendChild(opt);
        });
    }

    var tbody = document.getElementById("configAdminsBody");
    var html = "";

    admins.forEach(function(a) {
        var rolClass = a.rol === "superadmin" ? "text-brand-700 bg-brand-50" : "text-gray-600 bg-gray-100";
        var sedeText = a.sede_nombre || "Todas (superadmin)";

        html += '<tr class="border-b border-gray-50">'
            + '<td class="py-3 text-gray-700 text-xs">' + escaparHtml(a.email) + '</td>'
            + '<td class="py-3 text-gray-600 text-xs">' + escaparHtml(sedeText) + '</td>'
            + '<td class="py-3"><span class="px-2 py-0.5 rounded-md text-[11px] font-medium ' + rolClass + '">' + escaparHtml(a.rol) + '</span></td>'
            + '<td class="py-3 text-right">'
            + '<button onclick="eliminarAdmin(' + a.id + ',\'' + escaparHtml(a.email).replace(/'/g, "\\'") + '\')" class="text-xs px-2 py-1 rounded text-red-500 hover:bg-red-50 transition-colors">Eliminar</button>'
            + '</td></tr>';
    });

    tbody.innerHTML = html;
}

async function crearAdmin() {
    var email = document.getElementById("inputAdminEmail").value.trim();
    if (!email) {
        mostrarToast("Escribe el email del admin", "error");
        return;
    }

    var selectSede = document.getElementById("selectAdminSede");
    var sedeId = selectSede.value ? parseInt(selectSede.value) : null;
    var rol = document.getElementById("selectAdminRol").value;

    var token = await obtenerToken();
    if (!token) return;

    var body = { email: email, rol: rol };
    if (sedeId) body.sede_id = sedeId;

    var res = await fetchConReintentos(API_URL + "/admin/admins", {
        method: "POST", headers: authHeaders(token),
        body: JSON.stringify(body)
    });

    if (!res) return;
    if (res.status === 400) {
        var err = await res.json();
        mostrarToast(err.detail || "Error al crear admin", "error");
        return;
    }

    document.getElementById("inputAdminEmail").value = "";
    mostrarToast("Admin agregado correctamente", "success");
    cargarConfigAdmins();
}

async function eliminarAdmin(adminId, email) {
    if (!confirm('Quitar acceso a "' + email + '"?')) return;

    var token = await obtenerToken();
    if (!token) return;

    var res = await fetchConReintentos(API_URL + "/admin/admins/" + adminId, {
        method: "DELETE", headers: { "Authorization": "Bearer " + token }
    });

    if (!res) return;
    if (res.status === 400) {
        var err = await res.json();
        mostrarToast(err.detail || "Error al eliminar", "error");
        return;
    }

    mostrarToast("Acceso removido", "success");
    cargarConfigAdmins();
}

// === Recordatorios (proximamente) ===

function abrirRecordatorios() {
    document.getElementById("modalRecordatorios").classList.remove("hidden");
}

function cerrarRecordatorios() {
    document.getElementById("modalRecordatorios").classList.add("hidden");
}

// === Finanzas ===

var quincenasOffset = 0;
var _quincenasData = null;
var _mercadoIdxActual = -1;

function abrirFinanzas() {
    quincenasOffset = 0;
    _mercadoIdxActual = -1;
    document.getElementById("modalFinanzas").classList.remove("hidden");
    cargarFinanzas();
}

function cerrarFinanzas() {
    document.getElementById("modalFinanzas").classList.add("hidden");
    document.getElementById("mercadoItemsPanel").classList.add("hidden");
}

async function cargarFinanzas() {
    var token = await obtenerToken();
    if (!token) return;

    var url = API_URL + "/finanzas/quincenas?offset=0&cantidad=5";
    if (sedeActual) url += "&sede_id=" + sedeActual;

    var res = await fetchConReintentos(url, { headers: { "Authorization": "Bearer " + token } });
    if (!res || res.status === 403) return;

    var data = await res.json();
    var fmt = function(n) { return "$" + Math.round(n || 0).toLocaleString("es-CO"); };

    precioTicket = data.precio_ticket || 0;
    document.getElementById("inputPrecioTicket").value = precioTicket > 0 ? precioTicket : "";

    // Tarjetas: quincena actual (índice 0)
    if (data.quincenas && data.quincenas.length > 0) {
        var q = data.quincenas[0];
        document.getElementById("fzPagadosTiq").textContent = q.pagados.tiquetes;
        document.getElementById("fzPagadosCOP").textContent = fmt(q.pagados.cop);
        document.getElementById("fzFiadosTiq").textContent = q.fiados.tiquetes;
        document.getElementById("fzFiadosCOP").textContent = fmt(q.fiados.cop);
        document.getElementById("fzEmpresaTiq").textContent = q.empresa.tiquetes;
        document.getElementById("fzEmpresaCOP").textContent = fmt(q.empresa.cop);
        document.getElementById("fzMercadoCOP").textContent = fmt(q.mercado.cop);
        var mAbr = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"];
        var pi = q.fecha_inicio.split("-"), pf = q.fecha_fin.split("-");
        var mi = mAbr[parseInt(pi[1])-1], mf = mAbr[parseInt(pf[1])-1];
        var rango = mi === mf
            ? parseInt(pi[2]) + "–" + parseInt(pf[2]) + " " + mi
            : parseInt(pi[2]) + " " + mi + "–" + parseInt(pf[2]) + " " + mf;
        document.getElementById("finanzasPeriodoLabel").textContent = "Sem. " + q.semana_iso + " · " + rango;
    }

    _quincenasData = data.quincenas;
    quincenasOffset = 0;
    renderTablaQuincenas(data.quincenas, 0);
    _actualizarNavQuincenas();

    if (_mercadoIdxActual >= 0) mostrarItemsMercado(_mercadoIdxActual);
}

async function cargarQuincenas() {
    var token = await obtenerToken();
    if (!token) return;

    var url = API_URL + "/finanzas/quincenas?offset=" + quincenasOffset + "&cantidad=5";
    if (sedeActual) url += "&sede_id=" + sedeActual;

    var res = await fetchConReintentos(url, { headers: { "Authorization": "Bearer " + token } });
    if (!res || res.status === 403) return;

    var data = await res.json();
    _quincenasData = data.quincenas;
    renderTablaQuincenas(data.quincenas, quincenasOffset);
    _actualizarNavQuincenas();
    document.getElementById("mercadoItemsPanel").classList.add("hidden");
    _mercadoIdxActual = -1;
}

function navegarQuincenas(delta) {
    var newOffset = quincenasOffset + delta;
    if (newOffset < 0) return;
    quincenasOffset = newOffset;
    _actualizarNavQuincenas();
    cargarQuincenas();
}

function _actualizarNavQuincenas() {
    var btnSig = document.getElementById("btnSiguienteQ");
    if (quincenasOffset === 0) {
        btnSig.disabled = true;
        btnSig.className = "text-xs text-gray-300 font-medium px-2 py-1 rounded cursor-not-allowed";
    } else {
        btnSig.disabled = false;
        btnSig.className = "text-xs text-brand-600 hover:text-brand-800 font-medium px-2 py-1 rounded hover:bg-brand-50 transition-colors";
    }
}

function renderTablaQuincenas(quincenas, offset) {
    var container = document.getElementById("tablaQuincenasContainer");
    if (!quincenas || quincenas.length === 0) {
        container.innerHTML = '<p class="text-center text-gray-400 text-sm py-6">Sin datos disponibles</p>';
        return;
    }

    var fmt = function(n) { return "$" + Math.round(n || 0).toLocaleString("es-CO"); };
    var mAbr = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"];
    var rangoLabel = function(q) {
        var pi = q.fecha_inicio.split("-"), pf = q.fecha_fin.split("-");
        var mi = mAbr[parseInt(pi[1])-1], mf = mAbr[parseInt(pf[1])-1];
        return mi === mf
            ? parseInt(pi[2]) + "–" + parseInt(pf[2]) + " " + mi
            : parseInt(pi[2]) + " " + mi + "–" + parseInt(pf[2]) + " " + mf;
    };

    var lbl = '<td class="py-1 px-2 w-16"></td>';

    // Fila 1: código semana YYYYWW
    var r1 = '<tr>' + lbl;
    quincenas.forEach(function(q, i) {
        var act = i === 0 && offset === 0;
        r1 += '<th class="text-center pt-3 pb-0.5 text-sm font-bold tracking-wider ' + (act ? 'text-brand-600' : 'text-gray-500') + '">' + q.semana_iso + '</th>';
    });
    r1 += '</tr>';

    // Fila 2: rango de fechas + mes abreviado
    var r2 = '<tr>' + lbl;
    quincenas.forEach(function(q, i) {
        var act = i === 0 && offset === 0;
        r2 += '<th class="text-center pb-2.5 text-[10px] font-medium border-b-2 ' + (act ? 'text-brand-400 border-brand-300' : 'text-gray-400 border-gray-200') + '">' + rangoLabel(q) + '</th>';
    });
    r2 += '</tr>';

    // Filas de datos
    var rowDefs = [
        { label: "Pagados", key: "pagados", lc: "text-green-700", vc: "text-green-700", sc: "text-green-500", bg: "bg-green-50/60" },
        { label: "Fiados",  key: "fiados",  lc: "text-red-600",   vc: "text-red-600",   sc: "text-red-400",   bg: "bg-red-50/60"   },
        { label: "Empresa", key: "empresa", lc: "text-teal-700",  vc: "text-teal-700",  sc: "text-teal-500",  bg: "bg-teal-50/60"  },
    ];
    var dataRows = "";
    rowDefs.forEach(function(rd) {
        dataRows += '<tr class="border-b border-gray-50">';
        dataRows += '<td class="py-2 px-2 text-[11px] font-bold ' + rd.lc + ' whitespace-nowrap">' + rd.label + '</td>';
        quincenas.forEach(function(q, i) {
            var act = i === 0 && offset === 0;
            var v = q[rd.key];
            dataRows += '<td class="py-1.5 text-center ' + (act ? rd.bg : '') + '">'
                + '<span class="block text-sm font-bold ' + rd.vc + '">' + (v.tiquetes || 0) + '</span>'
                + '<span class="block text-[10px] ' + rd.sc + '">' + fmt(v.cop) + '</span>'
                + '</td>';
        });
        dataRows += '</tr>';
    });

    // Fila mercado
    var mRow = '<tr><td class="py-2 px-2 text-[11px] font-bold text-orange-700 whitespace-nowrap">Mercado</td>';
    quincenas.forEach(function(q, i) {
        var act = i === 0 && offset === 0;
        mRow += '<td class="py-1.5 text-center ' + (act ? 'bg-orange-50/60' : '') + '">'
            + '<span class="block text-sm font-bold text-orange-700">' + fmt(q.mercado.cop) + '</span>'
            + '<button onclick="mostrarItemsMercado(' + i + ')" class="text-[10px] text-orange-400 hover:text-orange-600 underline block w-full text-center">ver/editar</button>'
            + '</td>';
    });
    mRow += '</tr>';

    container.innerHTML = '<table class="w-full border-collapse min-w-[480px]">'
        + '<thead>' + r1 + r2 + '</thead>'
        + '<tbody>' + dataRows + mRow + '</tbody>'
        + '</table>';
}

function mostrarItemsMercado(idx) {
    _mercadoIdxActual = idx;
    var panel = document.getElementById("mercadoItemsPanel");
    var lista = document.getElementById("mercadoItemsList");
    var titulo = document.getElementById("mercadoItemsTitulo");
    var fmt = function(n) { return "$" + Math.round(n || 0).toLocaleString("es-CO"); };

    if (!_quincenasData || !_quincenasData[idx]) { panel.classList.add("hidden"); return; }
    var q = _quincenasData[idx];
    var mAbrP = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"];
    var piP = q.fecha_inicio.split("-"), pfP = q.fecha_fin.split("-");
    var miP = mAbrP[parseInt(piP[1])-1], mfP = mAbrP[parseInt(pfP[1])-1];
    var rlP = miP === mfP
        ? parseInt(piP[2]) + "–" + parseInt(pfP[2]) + " " + miP
        : parseInt(piP[2]) + " " + miP + "–" + parseInt(pfP[2]) + " " + mfP;
    titulo.textContent = "Compras · Sem. " + q.semana_iso + " (" + rlP + ")";

    var items = q.mercado.items;
    if (!items || items.length === 0) {
        lista.innerHTML = '<p class="text-xs text-gray-400 py-2">Sin compras en este período</p>';
    } else {
        var html = "";
        items.forEach(function(item) {
            html += '<div id="itemRow_' + item.id + '" class="flex items-center gap-2 py-1.5 border-b border-orange-50 last:border-0">'
                + '<span class="text-xs font-semibold text-orange-700 w-20 shrink-0">' + fmt(item.monto) + '</span>'
                + '<span class="text-xs text-gray-600 flex-1 truncate">' + escaparHtml(item.descripcion) + '</span>'
                + '<span class="text-[10px] text-gray-300 shrink-0">' + item.fecha + '</span>'
                + '<button onclick="editarItemMercado(' + item.id + ',' + item.monto + ',\'' + escaparHtml(item.descripcion).replace(/'/g,"\\'") + '\')" class="text-[11px] text-gray-400 hover:text-brand-600 px-1 shrink-0" title="Editar">✎</button>'
                + '<button onclick="eliminarCompra(' + item.id + ')" class="text-[11px] text-red-300 hover:text-red-500 px-1 shrink-0" title="Eliminar">×</button>'
                + '</div>';
        });
        lista.innerHTML = html;
    }
    panel.classList.remove("hidden");
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function editarItemMercado(id, monto, descripcion) {
    var row = document.getElementById("itemRow_" + id);
    if (!row) return;
    row.innerHTML = '<input type="number" id="editMonto_' + id + '" value="' + monto + '" class="w-20 shrink-0 border border-orange-300 rounded px-1 py-0.5 text-xs font-semibold text-orange-700 outline-none">'
        + '<input type="text" id="editDesc_' + id + '" value="' + escaparHtml(descripcion) + '" class="flex-1 border border-gray-200 rounded px-1 py-0.5 text-xs text-gray-700 outline-none min-w-0">'
        + '<button onclick="guardarEdicionMercado(' + id + ')" class="text-[11px] text-green-600 hover:text-green-800 px-1.5 py-0.5 rounded bg-green-50 shrink-0">✓</button>'
        + '<button onclick="mostrarItemsMercado(' + _mercadoIdxActual + ')" class="text-[11px] text-gray-400 hover:text-gray-600 px-1 shrink-0">✕</button>';
}

async function guardarEdicionMercado(id) {
    var monto = parseFloat(document.getElementById("editMonto_" + id).value);
    var desc = document.getElementById("editDesc_" + id).value.trim();
    if (!monto || monto <= 0) { mostrarToast("Monto inválido", "error"); return; }
    var token = await obtenerToken();
    if (!token) return;
    var res = await fetchConReintentos(API_URL + "/mercado/" + id, {
        method: "PUT", headers: authHeaders(token),
        body: JSON.stringify({ monto: monto, descripcion: desc })
    });
    if (!res) return;
    mostrarToast("Compra actualizada", "success");
    cargarFinanzas();
}

async function guardarPrecioTicket() {
    var precio = parseFloat(document.getElementById("inputPrecioTicket").value);
    if (isNaN(precio) || precio < 0) {
        mostrarToast("Ingresa un precio valido (0 o mayor)", "error");
        return;
    }
    var token = await obtenerToken();
    if (!token) return;
    var url = API_URL + "/configuracion/precio-ticket";
    if (sedeActual) url += "?sede_id=" + sedeActual;
    var res = await fetchConReintentos(url, {
        method: "PUT", headers: authHeaders(token),
        body: JSON.stringify({ precio_ticket: precio })
    });
    if (!res) return;
    precioTicket = precio;
    mostrarToast("Precio actualizado: $" + precio.toLocaleString("es-CO") + " COP", "success");
}

async function registrarCompra() {
    var monto = parseFloat(document.getElementById("inputCompraMontoF").value);
    if (!monto || monto <= 0) { mostrarToast("Ingresa un monto valido", "error"); return; }
    var desc = document.getElementById("inputCompraDescF").value.trim();
    var token = await obtenerToken();
    if (!token) return;
    var body = { monto: monto };
    if (desc) body.descripcion = desc;
    if (sedeActual) body.sede_id = sedeActual;
    var url = API_URL + "/mercado/";
    if (sedeActual) url += "?sede_id=" + sedeActual;
    var res = await fetchConReintentos(url, {
        method: "POST", headers: authHeaders(token),
        body: JSON.stringify(body)
    });
    if (!res) return;
    document.getElementById("inputCompraMontoF").value = "";
    document.getElementById("inputCompraDescF").value = "";
    mostrarToast("Compra registrada", "success");
    cargarFinanzas();
}

async function eliminarCompra(compraId) {
    if (!confirm("Eliminar esta compra?")) return;
    var token = await obtenerToken();
    if (!token) return;
    var url = API_URL + "/mercado/" + compraId;
    if (sedeActual) url += "?sede_id=" + sedeActual;
    var res = await fetchConReintentos(url, {
        method: "DELETE", headers: { "Authorization": "Bearer " + token }
    });
    if (!res) return;
    mostrarToast("Compra eliminada", "info");
    cargarFinanzas();
}
