// === Configuracion de Supabase Auth ===
const SUPABASE_URL = "https://gsjlkppgsyjoddihuuup.supabase.co";
const SUPABASE_ANON_KEY = "sb_publishable_ECw9E40Z7N5FbQ54LP9kgQ_mOMz_289";
const supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

const API_URL = window.location.hostname === "localhost"
    ? "http://localhost:8000"
    : "https://tiqueteras-app.onrender.com";

let usuarioActualId = null;
let usuarioActualNombre = "";
let diasGlobales = [];

// === Indicador de carga ===

function mostrarCarga(msg) {
    const el = document.getElementById("loadingOverlay");
    if (el) {
        document.getElementById("loadingMsg").textContent = msg || "Conectando con el servidor...";
        el.classList.remove("hidden");
    }
}

function ocultarCarga() {
    const el = document.getElementById("loadingOverlay");
    if (el) el.classList.add("hidden");
}

// === Autenticacion ===

async function obtenerToken() {
    const { data: { session } } = await supabaseClient.auth.getSession();
    if (!session) {
        window.location.href = "login.html";
        return null;
    }
    return session.access_token;
}

function authHeaders(token) {
    return {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`
    };
}

async function cerrarSesion() {
    await supabaseClient.auth.signOut();
    window.location.href = "login.html";
}

// Verificar sesion al cargar
supabaseClient.auth.getSession().then(({ data: { session } }) => {
    if (!session) {
        window.location.href = "login.html";
    } else {
        cargarDashboard();
    }
});

// === Fetch con reintentos (para cold start de Render) ===

async function fetchConReintentos(url, opciones, maxIntentos) {
    maxIntentos = maxIntentos || 3;
    for (let intento = 1; intento <= maxIntentos; intento++) {
        try {
            const res = await fetch(url, opciones);

            if (res.status === 401) {
                await cerrarSesion();
                return null;
            }

            if (!res.ok) {
                throw new Error("HTTP " + res.status);
            }

            return res;
        } catch (err) {
            if (intento < maxIntentos) {
                // Esperar antes de reintentar (3s, 6s)
                mostrarCarga("Reintentando conexion... (intento " + intento + "/" + maxIntentos + ")");
                await new Promise(function(r) { setTimeout(r, 3000 * intento); });
            } else {
                ocultarCarga();
                console.error("Error de conexion tras " + maxIntentos + " intentos:", err);
                return null;
            }
        }
    }
    return null;
}

// === Utilidades ===

function escaparHtml(texto) {
    const div = document.createElement("div");
    div.textContent = texto;
    return div.innerHTML;
}

function inicialDia(fechaStr) {
    const dateObj = new Date(fechaStr + 'T00:00:00');
    const dia = dateObj.getDay();
    return ["D", "L", "M", "Mi", "J", "V", "S"][dia];
}

// === Dashboard ===

async function cargarDashboard() {
    const token = await obtenerToken();
    if (!token) return;

    mostrarCarga("Cargando datos del servidor...");

    const res = await fetchConReintentos(
        API_URL + "/dashboard",
        { headers: { "Authorization": "Bearer " + token } }
    );

    ocultarCarga();

    if (!res) return;

    const data = await res.json();
    diasGlobales = data.dias_globales || [];
    document.getElementById("metricHoy").innerText = data.metricas.almuerzos_hoy;
    renderizarCalendario(data);
}

function renderizarCalendario(data) {
    const thead = document.getElementById("calendarHead");
    const tbody = document.getElementById("calendarBody");

    let htmlHead = '<tr><th class="p-3 w-48 sticky left-0 bg-gray-100 z-20">Persona</th>';
    data.fechas_columnas.forEach(function(fecha) {
        const dateObj = new Date(fecha + 'T00:00:00');
        const isSunday = dateObj.getDay() === 0;
        const isToday = fecha === new Date().toISOString().split('T')[0];
        const isGlobal = diasGlobales.includes(fecha);
        const nombreDia = dateObj.toLocaleDateString('es-CO', { weekday: 'short' });

        const bgClass = isToday ? 'bg-blue-100' : isGlobal ? 'bg-red-100' : '';
        const textClass = isSunday ? 'text-red-500' : '';

        htmlHead += '<th class="p-2 text-center min-w-[80px] border-l cursor-pointer select-none ' + bgClass + ' ' + textClass + '"'
            + ' onclick="toggleDiaGlobal(\'' + fecha + '\')"'
            + ' title="Click para bloquear/desbloquear este dia">'
            + '<div class="capitalize text-sm">' + nombreDia + '</div>'
            + '<div class="text-[10px] font-normal text-gray-500 mt-1 tracking-tighter">' + escaparHtml(fecha) + '</div>'
            + (isGlobal ? '<div class="text-[9px] text-red-600 font-bold mt-0.5">BLOQUEADO</div>' : '')
            + '</th>';
    });
    htmlHead += '</tr>';
    thead.innerHTML = htmlHead;

    let htmlBody = "";
    data.usuarios.forEach(function(user) {
        const nombreSafe = escaparHtml(user.nombre);
        var saldoText = user.saldo_actual < 0
            ? '<span class="text-red-500 font-bold ml-2 text-xs">(-' + Math.abs(user.saldo_actual) + ')</span>'
            : '<span class="text-blue-500 font-bold ml-2 text-xs">(+' + user.saldo_actual + ')</span>';

        htmlBody += '<tr class="border-b user-row hover:bg-gray-50" data-nombre="' + nombreSafe.toLowerCase() + '">'
            + '<td class="p-3 font-medium cursor-pointer text-gray-800 hover:text-blue-600 sticky left-0 bg-white z-10 border-r"'
            + ' onclick="abrirModalPerfil(' + user.id + ', \'' + nombreSafe.replace(/'/g, "\\'") + '\', ' + user.saldo_actual + ', \'' + escaparHtml(user.fecha_cobertura) + '\')">'
            + nombreSafe + ' ' + saldoText
            + '</td>';

        user.calendario.forEach(function(dia) {
            var isToday = dia.es_hoy;
            var inicial = inicialDia(dia.fecha);
            var todayBg = isToday ? 'bg-blue-50' : '';

            var colorClass = "bg-white";
            var textColor = "text-gray-400";

            if (dia.estado === "past_covered") { colorClass = "bg-green-800 opacity-30"; textColor = "text-white"; }
            if (dia.estado === "past_fiado") { colorClass = "bg-orange-700 opacity-35"; textColor = "text-white"; }
            if (dia.estado === "past_absence") { colorClass = "bg-gray-300 opacity-40"; textColor = "text-gray-500"; }
            if (dia.estado === "past_global_blocked") { colorClass = "bg-red-800 opacity-30"; textColor = "text-white"; }

            if (dia.estado === "covered") { colorClass = "bg-green-500 shadow-sm"; textColor = "text-white"; }
            if (dia.estado === "fiado") { colorClass = "bg-orange-400 shadow-sm"; textColor = "text-white"; }
            if (dia.estado === "sin_cobertura") { colorClass = "bg-gray-200"; textColor = "text-gray-400"; }
            if (dia.estado === "absence") { colorClass = "bg-red-500 shadow-sm"; textColor = "text-white"; }
            if (dia.estado === "sunday_blocked") { colorClass = "bg-gray-100"; textColor = "text-gray-400"; }
            if (dia.estado === "global_blocked") { colorClass = "bg-red-700 shadow-sm"; textColor = "text-white"; }

            htmlBody += '<td class="p-1 min-w-[80px] border-l ' + todayBg + '">'
                + '<div onclick="toggleExcepcion(' + user.id + ', \'' + dia.fecha + '\')"'
                + ' class="h-10 w-full rounded ' + colorClass + ' cursor-pointer transition-all hover:opacity-80 flex justify-center items-center text-xs font-medium ' + textColor + '"'
                + ' title="' + dia.fecha + ' - ' + dia.estado + '">'
                + inicial
                + '</div></td>';
        });
        htmlBody += '</tr>';
    });
    tbody.innerHTML = htmlBody;
}

document.getElementById("searchInput").addEventListener("input", function(e) {
    var term = e.target.value.toLowerCase();
    document.querySelectorAll(".user-row").forEach(function(row) {
        row.style.display = row.dataset.nombre.includes(term) ? "" : "none";
    });
});

// === Acciones autenticadas ===

async function toggleDiaGlobal(fecha) {
    var token = await obtenerToken();
    if (!token) return;
    await fetchConReintentos(API_URL + "/dias-globales/", {
        method: "POST",
        headers: authHeaders(token),
        body: JSON.stringify({ fecha: fecha })
    });
    cargarDashboard();
}

async function toggleExcepcion(userId, fecha) {
    var token = await obtenerToken();
    if (!token) return;
    await fetchConReintentos(API_URL + "/usuarios/" + userId + "/excepcion", {
        method: "POST",
        headers: authHeaders(token),
        body: JSON.stringify({ fecha: fecha })
    });
    cargarDashboard();
}

function formatearFechaCompleta(fechaStr) {
    if (!fechaStr || fechaStr === 'Sin saldo' || fechaStr === 'En deuda' || fechaStr.includes('Suficiente')) {
        return fechaStr;
    }
    var parts = fechaStr.split('-');
    var dateObj = new Date(parts[0], parts[1] - 1, parts[2]);
    return dateObj.toLocaleDateString('es-CO', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
}

function abrirModalPerfil(id, nombre, saldo, cobertura) {
    usuarioActualId = id;
    usuarioActualNombre = nombre;
    document.getElementById("modalNombre").innerText = nombre;

    var saldoEl = document.getElementById("modalSaldo");
    if (saldo < 0) {
        saldoEl.innerText = Math.abs(saldo) + " tickets en deuda";
        saldoEl.className = "font-bold text-red-600 text-xl";
    } else {
        saldoEl.innerText = saldo + " tickets a favor";
        saldoEl.className = "font-bold text-blue-600 text-xl";
    }

    document.getElementById("modalCobertura").innerText = formatearFechaCompleta(cobertura);
    document.getElementById("modalPerfil").classList.remove("hidden");
}

function cerrarModal() {
    document.getElementById("modalPerfil").classList.add("hidden");
    document.getElementById("inputTickets").value = "";
}

async function ajustarTickets(accion) {
    var cantidad = parseInt(document.getElementById("inputTickets").value);
    if (!cantidad || cantidad <= 0) {
        alert("Ingresa un numero valido mayor a 0.");
        return;
    }
    if (accion === 'quitar') cantidad = -cantidad;

    var token = await obtenerToken();
    if (!token) return;
    await fetchConReintentos(API_URL + "/usuarios/" + usuarioActualId + "/tickets", {
        method: "POST",
        headers: authHeaders(token),
        body: JSON.stringify({ cantidad: cantidad })
    });
    cerrarModal();
    cargarDashboard();
}

async function eliminarUsuario() {
    if (!confirm('Estas seguro de eliminar a "' + usuarioActualNombre + '"? Se borraran todos sus tickets y excepciones.')) {
        return;
    }
    var token = await obtenerToken();
    if (!token) return;
    await fetchConReintentos(API_URL + "/usuarios/" + usuarioActualId, {
        method: "DELETE",
        headers: { "Authorization": "Bearer " + token }
    });
    cerrarModal();
    cargarDashboard();
}

async function abrirModalUsuarioNuevo() {
    var nombre = prompt("Nombre de la nueva persona:");
    if (nombre && nombre.trim() !== "") {
        var token = await obtenerToken();
        if (!token) return;
        await fetchConReintentos(API_URL + "/usuarios/", {
            method: "POST",
            headers: authHeaders(token),
            body: JSON.stringify({ nombre: nombre.trim() })
        });
        cargarDashboard();
    }
}

async function descargarExcel() {
    var token = await obtenerToken();
    if (!token) return;
    var hoy = new Date().toISOString().split('T')[0];

    mostrarCarga("Generando archivo Excel...");

    try {
        var res = await fetch(API_URL + "/exportar?fecha=" + hoy, {
            headers: { "Authorization": "Bearer " + token }
        });
        ocultarCarga();
        if (!res.ok) { alert("Error al exportar"); return; }
        var blob = await res.blob();
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = "comensales_" + hoy + ".xlsx";
        a.click();
        URL.revokeObjectURL(url);
    } catch (err) {
        ocultarCarga();
        alert("Error de conexion al exportar. Intenta de nuevo.");
    }
}
