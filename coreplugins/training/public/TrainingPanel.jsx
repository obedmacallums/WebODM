import React from 'react';
import PropTypes from 'prop-types';
import ErrorMessage from 'webodm/components/ErrorMessage';
import { _ } from 'webodm/classes/gettext';
import LabelEditor, { MODE_NONE, MODE_POLYGON, MODE_BRUSH, MODE_ERASER, MODE_SELECT }
  from './LabelEditor';
import { createLabelLayer } from './labelLayer';
import { shouldRebuildEditor } from './panelLifecycle';

/**
 * Panel de etiquetado sobre el mapa de una tarea (D1).
 *
 * Solo ofrece los datasets que ya incluyen esta tarea: un dataset agrupa varias tareas y se crea
 * desde la página global, así que aquí la pregunta no es «qué dataset creo» sino «en cuál de los
 * míos estoy etiquetando ahora».
 */
export default class TrainingPanel extends React.Component {
  static defaultProps = {
    isShowed: false
  };

  static propTypes = {
    onClose: PropTypes.func.isRequired,
    tasks: PropTypes.array.isRequired,
    map: PropTypes.object.isRequired,
    isShowed: PropTypes.bool
  };

  constructor(props){
    super(props);

    this.state = {
      loading: false,
      error: '',
      datasets: [],
      datasetId: null,
      classIndex: 1,
      mode: MODE_NONE,
      radiusM: 3,
      labels: [],
      saving: false,
      exports: [],
      selectedId: null
    };
  }

  componentDidMount(){
    if (this.props.isShowed) this.loadDatasets();
  }

  componentDidUpdate(prevProps, prevState){
    if (this.props.isShowed && !prevProps.isShowed) this.loadDatasets();
    if (!this.props.isShowed && prevProps.isShowed) this.teardownEditor();

    // La reconstrucción no puede colgar solo de «¿cambió el dataset?»: al reabrir el panel sobre
    // el mismo dataset no cambia nada, y el editor que `teardownEditor` destruyó al cerrar no
    // volvería nunca (ver `panelLifecycle.js`).
    if (shouldRebuildEditor(
          {isShowed: this.props.isShowed, datasetId: this.state.datasetId,
           hasEditor: !!this.editor},
          {previousDatasetId: prevState.datasetId})){
      this.onDatasetChanged();
    }
  }

  componentWillUnmount(){
    this.teardownEditor();
  }

  task(){ return this.props.tasks[0]; }

  apiBase(){ return `/api/plugins/training`; }

  labelsUrl(extra){
    const suffix = extra ? `/${extra}` : '';
    return `${this.apiBase()}/datasets/${this.state.datasetId}/tasks/${this.task().id}/labels${suffix}`;
  }

  dataset(){
    return this.state.datasets.find(d => d.id === this.state.datasetId) || null;
  }

  // --- Carga --------------------------------------------------------------------------

  loadDatasets = () => {
    this.setState({loading: true, error: ''});
    $.ajax({url: `${this.apiBase()}/datasets`, type: 'GET', contentType: 'application/json'})
      .done(datasets => {
        const taskId = String(this.task().id);
        const mine = (datasets || []).filter(d =>
          (d.tasks || []).some(t => String(t.task_id) === taskId));
        this.setState({
          datasets: mine,
          datasetId: mine.length ? (this.state.datasetId || mine[0].id) : null,
          loading: false
        });
      })
      .fail(() => this.setState({loading: false, error: _("Could not load datasets.")}));
  };

  onDatasetChanged(){
    this.teardownEditor();
    if (!this.state.datasetId) return;

    this.layer = createLabelLayer(this.props.map, {onSelect: this.selectLabel});
    this.layer.setClasses(this.dataset() ? this.dataset().classes : []);

    this.editor = new LabelEditor({
      map: this.props.map,
      classes: this.dataset() ? this.dataset().classes : [],
      classIndex: this.state.classIndex,
      radiusM: this.state.radiusM,
      onCreate: this.createLabel,
      // Escape suelta la herramienta: el panel es quien manda sobre el modo, así que el editor
      // avisa en vez de cambiarlo por su cuenta y dejar los botones desincronizados.
      onExitMode: () => this.setMode(MODE_NONE)
    });
    this.editor.setMode(this.state.mode);

    this.loadLabels();
    this.loadExports();
  }

  // --- Selección y edición (FR-013) ---------------------------------------------------

  /**
   * Clic sobre una etiqueta dibujada.
   *
   * Solo selecciona cuando no se está dibujando: durante un trazado, un clic sobre una etiqueta
   * existente es un vértice más, no un intento de seleccionarla.
   */
  selectLabel = (label, layer) => {
    if (this.editor && this.editor.isActive()) return;

    this.setState({selectedId: label.id});
    if (this.layer) this.layer.setSelected(label.id);
    // El estilo cambia al seleccionar, así que la capa se redibuja: hay que pedir la nueva, no
    // la que llegó en el evento, o los manejadores de vértices quedarían sobre una capa muerta.
    if (this.editor) {
      this.editor.startEditing(this.layer.layerFor(label.id) || layer, {
        onChange: ring => this.saveGeometry(label.id, ring),
        onStop: () => this.setState({selectedId: null})
      });
    }
  };

  clearSelection = () => {
    if (this.editor) this.editor.stopEditing();
    if (this.layer) this.layer.setSelected(null);
    this.setState({selectedId: null});
  };

  selectedLabel(){
    return this.state.labels.find(l => l.id === this.state.selectedId) || null;
  }

  /** Persiste la geometría tras mover, insertar o borrar un vértice. */
  saveGeometry = (labelId, ring) => {
    const geometry = ring.map(ll => [ll.lng, ll.lat]);
    $.ajax({url: this.labelsUrl(labelId), type: 'PATCH', contentType: 'application/json',
            data: JSON.stringify({geometry})})
      .done(saved => {
        // Se guarda lo que devuelve el servidor: viene ya simplificado (FR-015), así que la
        // geometría local y la almacenada no divergen tras el primer arrastre.
        const labels = this.state.labels.map(l => l.id === labelId ? saved : l);
        this.setState({labels});
      })
      .fail(xhr => this.setState({
        error: (xhr.responseJSON && xhr.responseJSON.error) || _("Could not save the change.")
      }));
  };

  deleteSelected = () => {
    const selected = this.selectedLabel();
    if (!selected) return;
    this.clearSelection();
    this.deleteLabel(selected.id);
  };

  /** Reasigna la etiqueta seleccionada a la clase activa. */
  reassignSelected = () => {
    const selected = this.selectedLabel();
    if (!selected) return;

    $.ajax({url: this.labelsUrl(selected.id), type: 'PATCH', contentType: 'application/json',
            data: JSON.stringify({class_index: this.state.classIndex})})
      .done(saved => {
        const labels = this.state.labels.map(l => l.id === saved.id ? saved : l);
        this.setState({labels});
        if (this.layer) this.layer.setLabels(labels);
      })
      .fail(() => this.setState({error: _("Could not change the class.")}));
  };

  loadLabels = () => {
    if (!this.state.datasetId) return;
    $.ajax({url: this.labelsUrl(), type: 'GET', contentType: 'application/json'})
      .done(labels => {
        this.setState({labels: labels || []});
        if (this.layer) this.layer.setLabels(labels || []);
        // Una selección que ya no existe se suelta: dejarla apuntaría a una etiqueta ausente y
        // el botón de borrar no haría nada sin decir por qué.
        if (this.state.selectedId &&
            !(labels || []).some(l => l.id === this.state.selectedId)) this.clearSelection();
      })
      .fail(() => this.setState({error: _("Could not load labels.")}));
  };

  /**
   * Estado de las exportaciones del dataset activo.
   *
   * El panel no lanza exportaciones —eso vive en la página global, donde está el dataset entero—
   * pero sí las muestra: quien está etiquetando quiere saber si la que dejó corriendo ya terminó
   * sin tener que abrir otra pestaña para averiguarlo.
   */
  loadExports = () => {
    if (!this.state.datasetId) return;
    $.ajax({url: `${this.apiBase()}/datasets/${this.state.datasetId}/exports`, type: 'GET'})
      .done(exports => {
        this.setState({exports: exports || []});
        const running = (exports || []).some(e => e.status === 'running');
        // El sondeo solo existe mientras algo corre, y se para al cerrar el panel: dejarlo vivo
        // llenaría el log de peticiones de una pestaña que nadie mira.
        if (running && !this.exportTimer){
          this.exportTimer = setInterval(this.loadExports, 2000);
        } else if (!running){
          this.stopExportPolling();
        }
      })
      .fail(() => this.stopExportPolling());
  };

  stopExportPolling(){
    if (this.exportTimer){
      clearInterval(this.exportTimer);
      this.exportTimer = null;
    }
  }

  teardownEditor(){
    this.stopExportPolling();
    if (this.editor){ this.editor.remove(); this.editor = null; }
    if (this.layer){ this.layer.remove(); this.layer = null; }
  }

  // --- Escritura ----------------------------------------------------------------------

  createLabel = (label) => {
    this.setState({saving: true, error: ''});
    $.ajax({url: this.labelsUrl(), type: 'POST', contentType: 'application/json',
            data: JSON.stringify(label)})
      .done(saved => {
        // Se añade el que devuelve el servidor y no el local: trae el `order` definitivo, que es
        // lo que decide quién gana en las zonas solapadas (FR-012), y la geometría ya simplificada.
        const labels = this.state.labels.concat([saved]);
        this.setState({labels, saving: false});
        if (this.layer) this.layer.setLabels(labels);
      })
      .fail(xhr => this.setState({
        saving: false,
        error: (xhr.responseJSON && xhr.responseJSON.error) || _("Could not save the label.")
      }));
  };

  deleteLabel = (labelId) => {
    $.ajax({url: this.labelsUrl(labelId), type: 'DELETE'})
      .done(() => {
        const labels = this.state.labels.filter(l => l.id !== labelId);
        this.setState({labels});
        if (this.layer) this.layer.setLabels(labels);
      })
      .fail(() => this.setState({error: _("Could not delete the label.")}));
  };

  // --- Interacción --------------------------------------------------------------------

  setMode = (mode) => {
    const next = this.state.mode === mode ? MODE_NONE : mode;
    this.setState({mode: next});
    if (this.editor) this.editor.setMode(next);
  };

  setClassIndex = (e) => {
    const classIndex = parseInt(e.target.value, 10);
    this.setState({classIndex});
    if (this.editor) this.editor.setClassIndex(classIndex);
  };

  setRadius = (e) => {
    const radiusM = parseFloat(e.target.value);
    this.setState({radiusM});
    if (this.editor) this.editor.setRadius(radiusM);
  };

  setDataset = (e) => {
    this.setState({datasetId: e.target.value || null});
  };

  render(){
    if (!this.props.isShowed) return (<div/>);

    const { datasets, datasetId, classIndex, mode, radiusM, labels, loading, exports } = this.state;
    const selected = this.selectedLabel();
    const running = exports.find(e => e.status === 'running');
    const ready = exports.filter(e => e.status === 'completed');
    const dataset = this.dataset();

    return (<div className="training-panel">
      <span className="close-button" onClick={this.props.onClose}/>
      <div className="title">{_("Training")}</div>

      <ErrorMessage bind={[this, 'error']} />

      {loading && <i className="fa fa-circle-notch fa-spin"/>}

      {!loading && !datasets.length &&
        <div className="no-datasets">
          {_("This task is not part of any dataset yet.")}
          {' '}
          <a href="/plugins/training/">{_("Create one")}</a>
        </div>}

      {!!datasets.length && <div className="training-controls">
        <div className="row-field">
          <label>{_("Dataset")}</label>
          <select className="form-control" value={datasetId || ''} onChange={this.setDataset}>
            {datasets.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </div>

        {dataset && <div className="row-field">
          <label>{_("Class")}</label>
          <select className="form-control" value={classIndex} onChange={this.setClassIndex}>
            {dataset.classes.map(c =>
              <option key={c.index} value={c.index}>{c.index} — {c.name}</option>)}
          </select>
          <span className="class-swatch" style={{
            background: (dataset.classes.find(c => c.index === classIndex) || {}).color
          }}/>
        </div>}

        <div className="row-field tools">
          {/* Sin una herramienta neutra explícita no hay forma evidente de dejar de dibujar, y
              los clics sobre las etiquetas nunca las seleccionan: durante un trazado un clic es
              un vértice. Antes había que recargar la página para salir del modo. */}
          <button type="button"
                  className={'btn btn-sm ' + (mode === MODE_NONE ? 'btn-primary' : 'btn-default')}
                  onClick={() => this.setMode(MODE_NONE)}
                  title={_("Stop drawing and click labels to select them.")}>
            <i className="fa fa-mouse-pointer"/> {_("Select")}
          </button>
          <button type="button"
                  className={'btn btn-sm ' + (mode === MODE_POLYGON ? 'btn-primary' : 'btn-default')}
                  onClick={() => this.setMode(MODE_POLYGON)}
                  title={_("Draw a polygon. Double click to close it.")}>
            <i className="fa fa-draw-polygon"/> {_("Polygon")}
          </button>
          <button type="button"
                  className={'btn btn-sm ' + (mode === MODE_BRUSH ? 'btn-primary' : 'btn-default')}
                  onClick={() => this.setMode(MODE_BRUSH)}
                  title={_("Paint with a brush of the radius below.")}>
            <i className="fa fa-paint-brush"/> {_("Brush")}
          </button>
          <button type="button"
                  className={'btn btn-sm ' + (mode === MODE_ERASER ? 'btn-primary' : 'btn-default')}
                  onClick={() => this.setMode(MODE_ERASER)}
                  title={_("Erase back to unlabeled — not to background.")}>
            <i className="fa fa-eraser"/> {_("Eraser")}
          </button>
        </div>

        {/* Seleccionar es lo que permite corregir en vez de volver a empezar (FR-013): se hace
            clicando la etiqueta en el mapa, y por eso el modo no necesita botón propio — basta
            con no estar dibujando. */}
        {!!selected && <div className="row-field selection">
          <div className="selection-title">
            {_("Selected")}: {selected.kind === 'stroke' ? _("stroke") : _("polygon")}
            {' · '}
            {selected.class_index === null
              ? _("eraser")
              : (dataset.classes.find(c => c.index === selected.class_index) || {}).name}
          </div>
          <div className="hint">
            {_("Drag a vertex to move it, click the outline to add one, right click a vertex to remove it.")}
          </div>
          <div className="selection-actions">
            <button type="button" className="btn btn-xs btn-default"
                    onClick={this.reassignSelected}
                    title={_("Assign it to the class selected above.")}>
              <i className="fa fa-tag"/> {_("Reassign")}
            </button>
            <button type="button" className="btn btn-xs btn-danger" onClick={this.deleteSelected}>
              <i className="fa fa-trash"/> {_("Delete")}
            </button>
            <button type="button" className="btn btn-xs btn-default" onClick={this.clearSelection}>
              {_("Deselect")}
            </button>
          </div>
        </div>}

        {!selected && mode === MODE_NONE && !!labels.length &&
          <div className="row-field hint">
            {_("Click a label on the map to edit or delete it.")}
          </div>}

        {mode !== MODE_NONE &&
          <div className="row-field hint">
            {_("Press Esc or click Select to stop drawing and edit existing labels.")}
          </div>}

        {(mode === MODE_BRUSH || mode === MODE_ERASER) && <div className="row-field">
          <label>{_("Radius")}: {radiusM} {_("m")}</label>
          <input type="range" min="0.5" max="20" step="0.5" value={radiusM}
                 onChange={this.setRadius}/>
          <div className="hint">{_("The radius is measured on the ground and stays constant as you zoom.")}</div>
        </div>}

        <div className="row-field summary">
          {labels.length} {_("labels")}
          {' '}
          <button type="button" className="btn btn-xs btn-default" onClick={this.loadLabels}>
            <i className="fa fa-sync"/>
          </button>
        </div>

        {running && <div className="row-field export-status">
          <i className="fa fa-circle-notch fa-spin"/>
          {' '}{_("Exporting")}: {running.progress || 0} %
        </div>}

        {!running && !!ready.length && <div className="row-field export-status">
          <a href={`${this.apiBase()}/datasets/${datasetId}/exports/${ready[ready.length - 1].id}/download`}>
            <i className="fa fa-download"/> {_("Download last export")}
          </a>
          {' '}
          <span className="text-muted">({ready[ready.length - 1].tile_count} {_("tiles")})</span>
        </div>}
      </div>}
    </div>);
  }
}
