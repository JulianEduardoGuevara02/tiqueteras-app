# Propuesta: Sistema de Pago Online de Tiqueteras

## Objetivo
Permitir que los empleados compren sus tickets de almuerzo en linea, eliminando el manejo de efectivo y automatizando el abono de tickets en el sistema.

## Pasarela recomendada: Wompi (Bancolombia)
- Sin costo mensual fijo
- Comision: 2.5% + $900 COP por transaccion
- Empresa colombiana, regulada por Bancolombia
- Sandbox gratuito para pruebas
- Acepta: tarjetas debito/credito, PSE, Nequi, Bancolombia

## Proyeccion de costos

Supuestos:
- Valor ticket de almuerzo: $12,000 COP
- Paquete minimo de compra: 20 tickets ($240,000 COP)
- 4 sedes con ~120 personas en total
- Compra promedio: 1 vez al mes por persona

| Escenario | Personas activas | Transacciones/mes | Valor total/mes | Comision Wompi/mes |
|-----------|-----------------|-------------------|-----------------|-------------------|
| Bajo | 60 | 60 | $14,400,000 | $414,000 |
| Medio | 90 | 90 | $21,600,000 | $621,000 |
| Alto | 120 | 120 | $28,800,000 | $828,000 |

**Costo operativo adicional en infraestructura: $0.** La implementacion corre sobre la misma infraestructura gratuita actual (Render + Supabase + Vercel).

## Comparativo: proceso actual vs propuesto

| Aspecto | Actual (efectivo) | Propuesto (online) |
|---------|-------------------|-------------------|
| Recaudo | Manual, la auxiliar recibe dinero | Automatico, llega directo a cuenta bancaria |
| Abono de tickets | Manual en la app | Automatico al confirmar pago |
| Riesgo de errores | Alto (contar efectivo, olvidar abonar) | Bajo (todo queda registrado) |
| Trazabilidad | Solo el log de la app | Comprobante bancario + log de la app |
| Disponibilidad | Solo en horario de la auxiliar | 24/7 |

## Alternativa B: Transferencia directa + verificacion en la app (RECOMENDADA)

### Como funciona
1. La persona transfiere a la cuenta de la empresa (PSE, Nequi, Daviplata, Bancolombia)
2. Sube el comprobante de pago en la app (foto o PDF)
3. La auxiliar revisa y aprueba con un boton → tickets se abonan automaticamente
4. Queda registro completo: comprobante + log de auditoria

### Comision: $0

### Proyeccion comparativa anual

| Concepto | Opcion A (Wompi) | Opcion B (Transferencia) |
|----------|-----------------|-------------------------|
| Comision/mes (escenario medio) | $621,000 | $0 |
| Comision/ano | ~$7,450,000 | $0 |
| Costo infraestructura | $0 | $0 |
| Tiempo de la auxiliar | Minimo (automatico) | ~15 min/dia (aprobar pagos) |
| Tramite inicial | Registro en Wompi (~3 dias) | Ninguno |

### Que se agrega a la app
- Boton "Reportar pago" en el perfil de cada persona
- Formulario: monto + comprobante (imagen/PDF)
- Panel de pagos pendientes para la auxiliar
- Boton "Aprobar" que abona tickets automaticamente
- Almacenamiento de comprobantes en Supabase Storage (1GB gratis)

### Ventajas
- Cero comision, ahorro de ~$7.5 millones/ano
- No depende de terceros ni tramites
- Funciona con cualquier banco o billetera digital
- Implementacion mas sencilla que una pasarela

### Desventaja
- La auxiliar debe aprobar manualmente (~15 min al dia)
- No es instantaneo: el abono depende de que la auxiliar revise

## Requisitos segun opcion

| Requisito | Opcion A (Wompi) | Opcion B (Transferencia) |
|-----------|-----------------|-------------------------|
| Cuenta bancaria empresarial | Si | Si (ya existe) |
| Registro en pasarela | Si (~3 dias) | No |
| Documentacion legal | RUT, camara de comercio | Ninguna |
| Desarrollo | ~1 semana | ~1 semana |

## Recomendacion final

**Opcion B (transferencia directa)** es la mas conveniente. Ahorra ~$7.5 millones/ano en comisiones, no requiere tramites con terceros, y la carga para la auxiliar es minima. Se implementa como canal complementario: quien quiera pagar por transferencia lo hace y sube su comprobante, quien prefiera pagar en efectivo sigue con el proceso actual.
