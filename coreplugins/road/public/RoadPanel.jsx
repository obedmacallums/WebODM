import React from 'react';
import PropTypes from 'prop-types';
import './RoadPanel.scss';
import ErrorMessage from 'webodm/components/ErrorMessage';
import { _ } from 'webodm/classes/gettext';
import bridge from './roadBridge';
import { colors } from './segmentStyle';

const POLL_INTERVAL = 1500;

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
      selectedAxis: "",
      selectedModel: "",
      selectedVariant: "original"
    };

    this._poll = null;
    this._published = {}; // analysisId -> L.FeatureGroup
  }

  // El panel opera sobre una única tarea: las métricas de un camino pertenecen a un DEM concreto,
  // y ofrecer un selector de eje que mezclara tareas invitaría a analizar una polilínea con el
  // modelo de elevación de otra.
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
  }

  handleBridgeError = (message) => this.setState({error: message});

  handleBridgeDeletion = (analysisId) => {
    delete this._published[analysisId];
    this.setState({analyses: this.state.analyses.filter(a => a.id !== analysisId)});
  }

  loadCapabilities(){
    $.getJSON(`${this.apiBase()}/capabilities`)
      .done(caps => {
        this.setState({
          capabilities: caps,
          selectedModel: caps.default_model || "",
          selectedAxis: caps.axes.length ? caps.axes[0].id : ""
        });
      })
      .fail(req => this.setState({error: this.errorFrom(req, _("No se pudieron leer las opciones de esta tarea."))}));
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

  errorFrom(req, fallback){
    const data = (req && req.responseJSON) || {};
    return data.error || fallback;
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
    $.getJSON(`${this.apiBase()}/analyses/${analysis.id}`)
      .done(detail => {
        const group = bridge.publishAnalysis(this.props.map, this.singleTask(), detail,
                                             detail.segments, {stored: true});
        this._published[analysis.id] = group;
      })
      .fail(req => this.setState({
        error: this.errorFrom(req, _("No se pudo dibujar el análisis."))
      }));
  }

  handleCalculate = () => {
    const { selectedAxis, selectedModel, selectedVariant } = this.state;
    if (!selectedAxis) return;

    this.setState({launching: true, error: ""});
    $.ajax({
      url: `${this.apiBase()}/analyses`,
      type: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({
        axis: {kind: 'annotation', ref: selectedAxis},
        model: selectedModel,
        variant: selectedVariant
      })
    }).done(() => {
      this.loadAnalyses();
      this.startPolling();
    }).fail(req => {
      this.setState({error: this.errorFrom(req, _("No se pudo lanzar el análisis."))});
    }).always(() => this.setState({launching: false}));
  }

  handleCancel = (analysis) => {
    $.ajax({url: `${this.apiBase()}/analyses/${analysis.id}/cancel`, type: 'POST'})
      .done(this.loadAnalyses)
      .fail(req => this.setState({error: this.errorFrom(req, _("No se pudo cancelar."))}));
  }

  renderAxisSelector(){
    const { capabilities, selectedAxis } = this.state;
    if (!capabilities) return null;

    if (!capabilities.annotations_available){
      return (<div className="road-notice">
        {_("El plugin de anotaciones no está disponible, así que no hay ejes que elegir.")}
      </div>);
    }
    if (!capabilities.axes.length){
      return (<div className="road-notice">
        {_("Esta tarea no tiene ninguna polilínea 2D. Traza una sobre el camino para poder analizarlo.")}
      </div>);
    }

    return (<div className="form-group">
      <label>{_("Eje")}</label>
      <select className="form-control" value={selectedAxis}
              onChange={e => this.setState({selectedAxis: e.target.value})}>
        {capabilities.axes.map(axis =>
          <option key={axis.id} value={axis.id}>
            {axis.name} ({axis.plan_length.toFixed(0)} m)
          </option>)}
      </select>
    </div>);
  }

  renderModelSelector(){
    const { capabilities, selectedModel } = this.state;
    if (!capabilities || capabilities.models.length < 2) return null;

    return (<div className="form-group">
      <label>{_("Modelo de elevación")}</label>
      <select className="form-control" value={selectedModel}
              onChange={e => this.setState({selectedModel: e.target.value, selectedVariant: 'original'})}>
        {capabilities.models.map(m => <option key={m} value={m}>{m.toUpperCase()}</option>)}
      </select>
    </div>);
  }

  renderAnalysis(analysis){
    const summary = analysis.summary || {};
    const isRunning = analysis.status === 'running';

    return (<li key={analysis.id} className={"road-analysis " + analysis.status}>
      <div className="road-analysis-header">
        <span className="road-analysis-name">{analysis.name}</span>
        {analysis.stale ? <span className="road-badge stale" title={_("El modelo de elevación cambió desde este cálculo")}>{_("desactualizado")}</span> : null}
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
        <div className="road-summary">
          <span>{summary.segment_count} {_("tramos")}</span>
          <span>{(summary.length || 0).toFixed(0)} m</span>
          {summary.mean_width !== null && summary.mean_width !== undefined ?
            <span>{_("ancho medio")} {summary.mean_width.toFixed(2)} m</span> : null}
          <span>{_("pendiente")} {(summary.min_grade || 0).toFixed(1)}% … {(summary.max_grade || 0).toFixed(1)}%</span>
        </div>
        : null}

      {analysis.status === 'failed' ?
        <div className="road-failed">{analysis.error}</div> : null}
      {analysis.status === 'canceled' ?
        <div className="road-failed">{_("Cancelado.")}</div> : null}
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
      <span className="road-legend-note">{_("El trazo discontinuo marca los tramos sin ancho medido.")}</span>
    </div>);
  }

  render(){
    const { capabilities, analyses, loading, launching, selectedAxis, error } = this.state;
    const task = this.singleTask();

    return (<div className="road-panel">
      <span className="close-button" onClick={this.props.onClose} />
      <div className="title">{_("Camino")}</div>
      <hr />

      <ErrorMessage bind={[this, "error"]} />

      {!task ?
        <div className="road-notice">
          {_("Abre una sola tarea para analizar su camino.")}
        </div>
        : loading ?
        <div className="road-notice">{_("Cargando…")}</div>
        : !capabilities ?
        <div className="road-notice">{error || _("Esta tarea no tiene modelo de elevación.")}</div>
        :
        <div>
          {this.renderAxisSelector()}
          {this.renderModelSelector()}

          <button className="btn btn-sm btn-primary road-calculate"
                  disabled={!selectedAxis || launching || !!this.state.running}
                  onClick={this.handleCalculate}>
            {launching ? _("Lanzando…") : _("Calcular")}
          </button>

          {this.state.running ?
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
