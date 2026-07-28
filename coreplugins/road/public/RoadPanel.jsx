import React from 'react';
import PropTypes from 'prop-types';
import './RoadPanel.scss';
import ErrorMessage from 'webodm/components/ErrorMessage';
import { _ } from 'webodm/classes/gettext';
import bridge from './roadBridge';
import { colors } from './segmentStyle';

const POLL_INTERVAL = 1500;
// El recoloreado es instantáneo en el cliente; persistirlo puede esperar a que el usuario suelte
// el deslizador. Sin esto, arrastrarlo dispara una petición por píxel movido.
const THRESHOLD_SAVE_DELAY = 600;

// El tercer elemento restringe el campo a un modo de detección: `break_threshold` solo tiene
// sentido buscando quiebres y `surface_tolerance` solo buscando separación. Mostrar el que no
// aplica sería una opción muerta, que es justo lo que `capabilities` existe para evitar.
const PARAM_FIELDS = [
  ['segment_length', () => _("Longitud de tramo (m)"), null],
  ['search_half_width', () => _("Semiancho de búsqueda (m)"), null],
  ['sample_step', () => _("Paso de muestreo (m)"), null],
  ['break_threshold', () => _("Umbral de quiebre (%)"), 'break'],
  ['surface_tolerance', () => _("Tolerancia de separación (m)"), 'surface'],
  ['min_consecutive_samples', () => _("Muestras seguidas para confirmar el borde"), null],
  ['coherence_window', () => _("Ventana de coherencia (tramos, 0 = sin reparar)"), null]
];

const EDGE_MODE_LABELS = {
  break: () => _("Quiebre de pendiente — talud o cuneta (camino)"),
  surface: () => _("Separación de la calzada — bordillo (calle)")
};

export default class RoadPanel extends React.Component {
  static propTypes = {
    onClose: PropTypes.func.isRequired,
    tasks: PropTypes.array.isRequired,
    tiles: PropTypes.array.isRequired,
    isShowed: PropTypes.bool.isRequired,
    map: PropTypes.object.isRequired
  }

  constructor(props){
    super(props);

    this.state = {
      capabilities: null,
      analyses: [],
      running: null,
      error: "",
      loading: true,
      launching: false,
      showParams: false,
      params: {},
      axisSource: 'annotation',
      uploadFile: null,
      pendingConfirm: null,
      selectedAxis: "",
      selectedModel: "",
      selectedVariant: "original"
    };

    this._poll = null;
    this._thresholdSaves = {}; // analysisId -> timeout del PATCH diferido
    this._published = {};      // analysisId -> L.FeatureGroup
  }

  // El panel opera sobre una única tarea: las métricas de un camino pertenecen a un DEM concreto,
  // y un selector de eje que mezclara tareas invitaría a analizar una polilínea con el modelo de
  // elevación de otra.
  singleTask = () => this.props.tasks.length === 1 ? this.props.tasks[0] : null;
  taskId = () => { const t = this.singleTask(); return t ? t.id : null; }
  apiBase = (taskId = this.taskId()) => `/api/plugins/road/task/${taskId}`;

  componentDidMount(){
    bridge.initBridge();
    bridge.setErrorNotifier(this.handleBridgeError);
    bridge.setDeletionNotifier(this.handleBridgeDeletion);
    if (this.singleTask()){
      this.loadCapabilities();
      this.loadAnalyses();
    }else{
      this.setState({loading: false});
    }
  }

  componentWillUnmount(){
    bridge.setErrorNotifier(null);
    bridge.setDeletionNotifier(null);
    this.stopPolling();
    Object.values(this._thresholdSaves).forEach(clearTimeout);
  }

  handleBridgeError = (message) => this.setState({error: message});

  handleBridgeDeletion = (analysisId) => {
    delete this._published[analysisId];
    this.setState({analyses: this.state.analyses.filter(a => a.id !== analysisId)});
  }

  errorFrom(req, fallback){
    const data = (req && req.responseJSON) || {};
    return data.error || fallback;
  }

  loadCapabilities(){
    $.getJSON(`${this.apiBase()}/capabilities`)
      .done(caps => {
        this.setState({
          capabilities: caps,
          params: Object.assign({}, caps.defaults),
          selectedModel: caps.default_model || "",
          selectedAxis: caps.axes.length ? caps.axes[0].id : ""
        });
      })
      .fail(req => this.setState({
        error: this.errorFrom(req, _("No se pudieron leer las opciones de esta tarea."))
      }));
  }

  loadAnalyses = () => {
    $.getJSON(`${this.apiBase()}/analyses`)
      .done(res => {
        this.setState({analyses: res.analyses, running: res.running, loading: false});
        res.analyses.forEach(a => this.publish(a));
        if (res.running) this.startPolling(); else this.stopPolling();
      })
      .fail(req => this.setState({
        loading: false,
        error: this.errorFrom(req, _("No se pudieron cargar los análisis."))
      }));
  }

  startPolling(){
    if (this._poll) return;
    this._poll = setInterval(this.loadAnalyses, POLL_INTERVAL);
  }

  stopPolling(){
    if (this._poll){
      clearInterval(this._poll);
      this._poll = null;
    }
  }

  // Publica el análisis en el mapa una sola vez: el sondeo de progreso vuelve a pasar por aquí
  // cada segundo y medio, y republicar duplicaría la capa en el panel del core.
  publish(analysis){
    if (analysis.status !== 'completed' || this._published[analysis.id]) return;
    this._published[analysis.id] = true; // reserva inmediata: el GET tarda y el sondeo no espera
    $.getJSON(`${this.apiBase()}/analyses/${analysis.id}`)
      .done(detail => {
        this._published[analysis.id] = bridge.publishAnalysis(
          this.props.map, this.singleTask(), detail, detail.segments, {stored: true});
      })
      .fail(req => {
        delete this._published[analysis.id];
        this.setState({error: this.errorFrom(req, _("No se pudo dibujar el análisis."))});
      });
  }

  republish(analysis){
    const group = this._published[analysis.id];
    if (group && group !== true) bridge.unpublishAnalysis(group);
    delete this._published[analysis.id];
    this.publish(analysis);
  }

  // Al pasar a `surface` se propone una ventana de coherencia de 2 si el usuario no la había
  // tocado: es el ajuste con el que el modo rinde en calle. Conveniencia de interfaz, no regla
  // del servidor (`006` FR-030) — el usuario puede volver a ponerla a 0.
  handleEdgeModeChange(mode){
    const params = Object.assign({}, this.state.params, {edge_mode: mode});
    const defaults = (this.state.capabilities || {}).defaults || {};
    const untouched = Number(params.coherence_window) === Number(defaults.coherence_window || 0);
    if (mode === 'surface' && untouched) params.coherence_window = 2;
    this.setState({params});
  }

  // --- Lanzar, recalcular, cancelar, borrar ----------------------------------------------

  canCalculate(){
    return this.state.axisSource === 'upload'
      ? !!this.state.uploadFile
      : !!this.state.selectedAxis;
  }

  // Dos cuerpos distintos para el mismo endpoint: JSON cuando el eje es una anotación, multipart
  // cuando se sube un archivo. `contentType: false` y `processData: false` son obligatorios en el
  // segundo caso: jQuery serializaría el FormData a texto y el archivo se perdería.
  requestOptions(confirm){
    const { axisSource, uploadFile, selectedAxis, selectedModel, selectedVariant, params } = this.state;
    const common = {model: selectedModel, variant: selectedVariant};

    if (axisSource === 'upload'){
      const form = new FormData();
      form.append('file', uploadFile);
      form.append('model', common.model);
      form.append('variant', common.variant);
      form.append('params', JSON.stringify(params));
      if (confirm) form.append('confirm', 'true');
      return {data: form, contentType: false, processData: false};
    }

    return {
      contentType: 'application/json',
      data: JSON.stringify(Object.assign({
        axis: {kind: 'annotation', ref: selectedAxis}, params
      }, common, confirm ? {confirm: true} : {}))
    };
  }

  handleCalculate = (confirm = false) => {
    if (!this.canCalculate()) return;

    this.setState({launching: true, error: ""});
    $.ajax(Object.assign({
      url: `${this.apiBase()}/analyses`,
      type: 'POST'
    }, this.requestOptions(confirm))).done(() => {
      this.setState({pendingConfirm: null});
      this.loadAnalyses();
      this.startPolling();
    }).fail(req => {
      const data = req.responseJSON || {};
      // 409 con `confirmation_required` no es un error que mostrar: es una pregunta que hacer.
      if (data.code === 'confirmation_required'){
        this.setState({pendingConfirm: {reason: data.reason, estimate: data.estimate}});
      }else{
        this.setState({error: this.errorFrom(req, _("No se pudo lanzar el análisis."))});
      }
    }).always(() => this.setState({launching: false}));
  }

  handleCancel = (analysis) => {
    $.ajax({url: `${this.apiBase()}/analyses/${analysis.id}/cancel`, type: 'POST'})
      .done(this.loadAnalyses)
      .fail(req => this.setState({error: this.errorFrom(req, _("No se pudo cancelar."))}));
  }

  handleDelete = (analysis) => {
    $.ajax({url: `${this.apiBase()}/analyses/${analysis.id}`, type: 'DELETE'})
      .done(() => {
        const group = this._published[analysis.id];
        if (group && group !== true) bridge.unpublishAnalysis(group);
        delete this._published[analysis.id];
        this.loadAnalyses();
      })
      .fail(req => this.setState({error: this.errorFrom(req, _("No se pudo eliminar."))}));
  }

  // La descarga la dispara el bridge con un enlace temporal por archivo y no con
  // `window.location.href`, que solo atiende una a la vez: pedir CSV y GeoJSON seguidos con el
  // segundo método se traía un único archivo.
  handleDownload = (analysis, format) => {
    bridge.downloadExport(this.taskId(), analysis.id, format);
  }

  // --- Semáforo -------------------------------------------------------------------------

  // Recoloreado inmediato en el cliente (SC-005) y persistencia diferida: los umbrales no
  // intervienen en el cálculo (FR-030), así que moverlos no pide nada al servidor salvo para que
  // el color sobreviva a una recarga.
  handleThresholdChange = (analysis, index, value) => {
    const thresholds = (analysis.color_thresholds || [8.0, 12.0]).slice();
    thresholds[index] = parseFloat(value);
    if (isNaN(thresholds[0]) || isNaN(thresholds[1])) return;
    // El backend rechaza aviso >= alerta; se evita mandar un estado que ya se sabe inválido.
    if (thresholds[0] >= thresholds[1]) return;

    this.setState({
      analyses: this.state.analyses.map(
        a => a.id === analysis.id ? Object.assign({}, a, {color_thresholds: thresholds}) : a)
    });
    bridge.applyThresholds(analysis.id, thresholds);

    clearTimeout(this._thresholdSaves[analysis.id]);
    this._thresholdSaves[analysis.id] = setTimeout(
      () => this.saveThresholds(analysis.id, thresholds), THRESHOLD_SAVE_DELAY);
  }

  saveThresholds(analysisId, thresholds){
    $.ajax({
      url: `${this.apiBase()}/analyses/${analysisId}`,
      type: 'PATCH',
      contentType: 'application/json',
      data: JSON.stringify({color_thresholds: thresholds})
    }).fail(req => this.setState({
      error: this.errorFrom(req, _("No se pudieron guardar los umbrales de color."))
    }));
  }

  // --- Render ---------------------------------------------------------------------------

  renderAxisSelector(){
    const { capabilities, selectedAxis, axisSource, uploadFile } = this.state;
    const hasAxes = capabilities.annotations_available && capabilities.axes.length > 0;

    return (<div className="road-axis">
      <div className="road-axis-source">
        <label>
          <input type="radio" checked={axisSource === 'annotation'} disabled={!hasAxes}
                 onChange={() => this.setState({axisSource: 'annotation'})} />
          {_("Anotación")}
        </label>
        <label>
          <input type="radio" checked={axisSource === 'upload'}
                 onChange={() => this.setState({axisSource: 'upload'})} />
          {_("Archivo GeoJSON")}
        </label>
      </div>

      {/* El motivo importa: sin `annotations` no hay nada que arreglar en esta tarea, mientras que
          con el plugin activo y sin polilíneas la acción es trazar una. */}
      {!capabilities.annotations_available ?
        <div className="road-notice">
          {_("El plugin de anotaciones no está disponible, así que no hay ejes que elegir. Puedes subir un archivo.")}
        </div>
        : !capabilities.axes.length ?
        <div className="road-notice">
          {_("Esta tarea no tiene ninguna polilínea 2D. Traza una sobre el camino, o sube un archivo.")}
        </div>
        : null}

      {axisSource === 'annotation' && hasAxes ?
        <div className="form-group">
          <label>{_("Eje")}</label>
          <select className="form-control" value={selectedAxis}
                  onChange={e => this.setState({selectedAxis: e.target.value})}>
            {capabilities.axes.map(axis =>
              <option key={axis.id} value={axis.id}>
                {axis.name} ({axis.plan_length.toFixed(0)} m)
              </option>)}
          </select>
        </div>
        : null}

      {axisSource === 'upload' ?
        <div className="form-group">
          <label>{_("Archivo")}</label>
          <input type="file" accept=".geojson,.json,application/geo+json,application/json"
                 onChange={e => this.setState({uploadFile: e.target.files[0] || null})} />
          <span className="road-range">
            {_("Un LineString 2D en EPSG:4326. Máximo")} {Math.round(
              (capabilities.max_upload_bytes || 0) / 1048576)} MB.
          </span>
          {uploadFile ? <div className="road-notice">{uploadFile.name}</div> : null}
        </div>
        : null}
    </div>);
  }

  renderModelSelector(){
    const { capabilities, selectedModel, selectedVariant } = this.state;
    const variants = (capabilities.variants || {})[selectedModel] || ['original'];

    return (<div>
      {capabilities.models.length > 1 ?
        <div className="form-group">
          <label>{_("Modelo de elevación")}</label>
          <select className="form-control" value={selectedModel}
                  onChange={e => this.setState({selectedModel: e.target.value,
                                                selectedVariant: 'original'})}>
            {capabilities.models.map(m => <option key={m} value={m}>{m.toUpperCase()}</option>)}
          </select>
        </div>
        : null}

      {/* Solo se ofrece cuando de verdad hay más de una: un desplegable de un elemento es una
          opción muerta que hace pensar que falta algo. */}
      {variants.length > 1 ?
        <div className="form-group">
          <label>{_("Variante")}</label>
          <select className="form-control" value={selectedVariant}
                  onChange={e => this.setState({selectedVariant: e.target.value})}>
            {variants.map(v => <option key={v} value={v}>
              {v === 'realigned' ? _("Realineado") : _("Original")}
            </option>)}
          </select>
        </div>
        : null}
    </div>);
  }

  renderParams(){
    const { capabilities, params, showParams } = this.state;
    const ranges = capabilities.ranges || {};

    return (<div className="road-params">
      <a onClick={() => this.setState({showParams: !showParams})}>
        {showParams ? _("Ocultar parámetros") : _("Ajustar parámetros")}
      </a>

      {showParams ?
        <div>
          <div className="form-group">
            <label>{_("Criterio de borde")}</label>
            <select className="form-control"
                    value={params.edge_mode || 'break'}
                    onChange={e => this.handleEdgeModeChange(e.target.value)}>
              {(capabilities.edge_modes || ['break']).map(mode =>
                <option key={mode} value={mode}>
                  {EDGE_MODE_LABELS[mode] ? EDGE_MODE_LABELS[mode]() : mode}
                </option>)}
            </select>
          </div>
          {PARAM_FIELDS.map(([key, label, onlyMode]) => {
            if (onlyMode && onlyMode !== (params.edge_mode || 'break')) return null;
            const [low, high] = ranges[key] || [];
            const integer = key === 'min_consecutive_samples' || key === 'coherence_window';
            return (<div className="form-group" key={key}>
              <label>{label()}</label>
              <input type="number" className="form-control"
                     min={low} max={high}
                     step={integer ? 1 : 0.05}
                     value={params[key] !== undefined ? params[key] : ''}
                     onChange={e => this.setState({
                       params: Object.assign({}, params, {[key]: e.target.value})
                     })} />
              <span className="road-range">{_("entre")} {low} {_("y")} {high}</span>
            </div>);
          })}
          <a onClick={() => this.setState({params: Object.assign({}, capabilities.defaults)})}>
            {_("Volver a los valores por defecto")}
          </a>
        </div>
        : null}
    </div>);
  }

  renderConfirm(){
    const { pendingConfirm } = this.state;
    if (!pendingConfirm) return null;
    const est = pendingConfirm.estimate || {};

    return (<div className="road-confirm">
      <p>
        {pendingConfirm.reason === 'replaces_existing' ?
          _("Ya hay un análisis para este eje. Al continuar, se sustituye por el nuevo.")
          : _("El análisis es costoso. Puedes lanzarlo igualmente.")}
      </p>
      <p className="road-estimate">
        {est.segments} {_("tramos")}, {est.samples} {_("muestras")},
        ~{Math.round(est.estimated_seconds || 0)} s
      </p>
      <button className="btn btn-xs btn-primary" onClick={() => this.handleCalculate(true)}>
        {_("Continuar")}
      </button>
      <button className="btn btn-xs btn-default"
              onClick={() => this.setState({pendingConfirm: null})}>
        {_("Cancelar")}
      </button>
    </div>);
  }

  renderThresholds(analysis){
    const [warn, alert] = analysis.color_thresholds || [8.0, 12.0];

    return (<div className="road-thresholds">
      <label>
        {_("Aviso")}
        <input type="range" min="1" max="49" step="0.5" value={warn}
               onChange={e => this.handleThresholdChange(analysis, 0, e.target.value)} />
        <span>{warn}%</span>
      </label>
      <label>
        {_("Alerta")}
        <input type="range" min="2" max="50" step="0.5" value={alert}
               onChange={e => this.handleThresholdChange(analysis, 1, e.target.value)} />
        <span>{alert}%</span>
      </label>
    </div>);
  }

  renderAnalysis(analysis){
    const summary = analysis.summary || {};
    const isRunning = analysis.status === 'running';

    return (<li key={analysis.id} className={"road-analysis " + analysis.status}>
      <div className="road-analysis-header">
        <span className="road-analysis-name">{analysis.name}</span>
        {analysis.stale ?
          <span className="road-badge stale"
                title={_("El modelo de elevación cambió desde este cálculo")}>
            {_("desactualizado")}
          </span> : null}
      </div>

      {isRunning ?
        <div className="road-progress">
          <div className="progress">
            <div className="progress-bar" role="progressbar"
                 style={{width: `${Math.round((analysis.progress || 0) * 100)}%`}} />
          </div>
          <button className="btn btn-xs btn-danger" onClick={() => this.handleCancel(analysis)}>
            {_("Cancelar")}
          </button>
        </div>
        : null}

      {analysis.status === 'completed' ?
        <div>
          <div className="road-summary">
            <span>{summary.segment_count} {_("tramos")}</span>
            <span>{(summary.length || 0).toFixed(0)} m</span>
            {summary.mean_width !== null && summary.mean_width !== undefined ?
              <span>{_("ancho medio")} {summary.mean_width.toFixed(2)} m</span> : null}
            <span>
              {_("pendiente")} {(summary.min_grade || 0).toFixed(1)}% … {(summary.max_grade || 0).toFixed(1)}%
            </span>
          </div>
          {this.renderThresholds(analysis)}
          <div className="road-downloads">
            {_("Descargar:")}
            <a onClick={() => this.handleDownload(analysis, 'csv')}>CSV</a>
            <a onClick={() => this.handleDownload(analysis, 'geojson')}>GeoJSON</a>
          </div>
        </div>
        : null}

      {analysis.status === 'failed' ? <div className="road-failed">{analysis.error}</div> : null}
      {analysis.status === 'canceled' ?
        <div className="road-failed">{_("Cancelado.")}</div> : null}

      {!isRunning ?
        <div className="road-actions">
          <a onClick={() => this.handleDelete(analysis)}>{_("Eliminar")}</a>
        </div>
        : null}
    </li>);
  }

  renderLegend(){
    const palette = colors();
    const entries = [
      [palette.ok, _("suave")],
      [palette.warn, _("moderada")],
      [palette.alert, _("fuerte")],
      [palette.unknown, _("sin datos")]
    ];
    return (<div className="road-legend">
      {entries.map(([color, label]) =>
        <span key={label}><i style={{background: color}} />{label}</span>)}
      <span className="road-legend-note">
        {_("El trazo discontinuo marca los tramos sin ancho medido.")}
      </span>
    </div>);
  }

  render(){
    const { capabilities, analyses, loading, launching, error, running } = this.state;
    const task = this.singleTask();

    return (<div className="road-panel">
      <span className="close-button" onClick={this.props.onClose} />
      <div className="title">{_("Camino")}</div>
      <hr />

      <ErrorMessage bind={[this, "error"]} />

      {!task ?
        <div className="road-notice">{_("Abre una sola tarea para analizar su camino.")}</div>
        : loading ?
        <div className="road-notice">{_("Cargando…")}</div>
        : !capabilities ?
        <div className="road-notice">{error || _("Esta tarea no tiene modelo de elevación.")}</div>
        :
        <div>
          {this.renderAxisSelector()}
          {this.renderModelSelector()}
          {this.renderParams()}

          <button className="btn btn-sm btn-primary road-calculate"
                  disabled={!this.canCalculate() || launching || !!running}
                  onClick={() => this.handleCalculate(false)}>
            {launching ? _("Lanzando…") : _("Calcular")}
          </button>

          {this.renderConfirm()}

          {running ?
            <div className="road-notice">{_("Ya hay un análisis en curso en esta tarea.")}</div>
            : null}

          <hr />
          {analyses.length ?
            <ul className="road-analyses">{analyses.map(a => this.renderAnalysis(a))}</ul>
            : <div className="road-notice">{_("Todavía no hay análisis en esta tarea.")}</div>}

          {analyses.some(a => a.status === 'completed') ? this.renderLegend() : null}
        </div>}
    </div>);
  }
}
