import React from 'react';
import PropTypes from 'prop-types';
import L from 'leaflet';
import './AnnotationsPanel.scss';
import ErrorMessage from 'webodm/components/ErrorMessage';
import PluginsAPI from 'webodm/classes/plugins/API';
import { _ } from 'webodm/classes/gettext';
import { unitSystem } from 'webodm/classes/Units';
import PolylineEditor from './PolylineEditor';
import bridge from './annotationsBridge';

export default class AnnotationsPanel extends React.Component {
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
      polylines: [],
      error: "",
      drawing: false,
      drawingMode: null,
      progressLength: 0,
      progressVertices: 0,
      pendingLatLngs: null,
      pendingName: "",
      pendingMode: "flat",
      pendingModel: null,
      pendingStep: null,
      coverageError: null,
      elevationCaps: null,
      saving: false,
      exportGeometry: "vertices",
      editingNameId: null,
      editingNameValue: "",
      editingGeometryId: null,
      selectedId: null
    };

    this.editor = new PolylineEditor(props.map);
    this._layers = {}; // polylineId -> L.Polyline
    this._coverageHighlightLayers = [];
    this._geometryRequests = {}; // polylineId -> jqXHR del PATCH de geometría en vuelo
  }

  singleTask = () => this.props.tasks.length === 1 ? this.props.tasks[0] : null;
  taskId = () => { const t = this.singleTask(); return t ? t.id : null; }
  apiBase = (taskId = this.taskId()) => `/api/plugins/annotations/task/${taskId}/polylines`;
  hasDem = () => {
    const { elevationCaps } = this.state;
    return !!(elevationCaps && elevationCaps.available && elevationCaps.available.length > 0);
  }

  componentDidMount(){
    bridge.initBridge();
    bridge.setErrorNotifier(this.handleBridgeError);
    PluginsAPI.Map.onAnnotationDeleted(this.handleAnnotationDeleted);
    this.loadAll();
    if (this.singleTask()) this.loadElevationCapabilities();
  }

  componentWillUnmount(){
    bridge.setErrorNotifier(null);
    PluginsAPI.Map.offAnnotationDeleted(this.handleAnnotationDeleted);
    Object.values(this._geometryRequests).forEach(req => req.abort());
    this._geometryRequests = {};
    this.editor.cancel();
    this.editor.stopEditing();
    this._clearCoverageHighlight();
  }

  // Errores de las acciones que el bridge atiende desde el panel de capas del core (borrar).
  handleBridgeError = (message) => {
    this.setState({error: message});
  }

  // Carga y publica las polilíneas de todas las tareas visibles (FR-030, FR-031): siguen
  // mostrándose en el mapa aunque el panel solo permita editar cuando hay una sola tarea.
  loadAll(){
    this.props.tasks.forEach(task => {
      $.getJSON(this.apiBase(task.id))
        .done(res => {
          if (res.version !== 1) return; // FR-040: contrato versionado
          res.polylines.forEach(p => this.publish(task, p, true));
          if (this.taskId() === task.id){
            this.setState({polylines: res.polylines});
          }
        })
        // Sin esto, una carga fallida dejaba el panel con el mismo aspecto que una tarea sin
        // polilíneas: el usuario no podía distinguir "no hay nada" de "no se pudo leer".
        .fail(req => this.setState({
          error: (req.responseJSON && req.responseJSON.error) ||
                 _("No se pudieron cargar las polilíneas guardadas.")
        }));
    });
  }

  loadElevationCapabilities(){
    $.getJSON(`/api/plugins/annotations/task/${this.taskId()}/elevation`)
      .done(caps => this.setState({elevationCaps: caps}));
  }

  publish = (task, polyline, stored) => {
    const layer = bridge.publishPolyline(this.props.map, task, polyline, {stored});
    this._layers[polyline.id] = layer;
    return layer;
  }

  handleAnnotationDeleted = (layer) => {
    const entry = Object.entries(this._layers).find(([, l]) => l === layer);
    if (!entry) return;
    const [id] = entry;
    delete this._layers[id];
    this.setState(prevState => ({
      polylines: prevState.polylines.filter(p => p.id !== id),
      selectedId: prevState.selectedId === id ? null : prevState.selectedId
    }));
  }

  // El tipo se elige antes de trazar, con el botón, y queda fijado para siempre: no hay
  // conversión posterior entre 2D y 3D.
  handleTrace = (mode) => {
    if (this.editor.isActive()){ this.editor.finish(); return; }
    const draped = mode === 'draped';
    const caps = this.state.elevationCaps;
    this.setState({error: "", progressLength: 0, progressVertices: 0, drawing: true, drawingMode: mode});
    this.editor.start({
      onProgress: (lengthM, nVertices) => this.setState({progressLength: lengthM, progressVertices: nVertices}),
      onComplete: (latlngs) => {
        this.setState({
          drawing: false,
          drawingMode: null,
          pendingLatLngs: latlngs,
          pendingName: "",
          pendingMode: mode,
          pendingModel: draped ? caps.default_model : null,
          pendingStep: draped ? caps.default_step : null,
          coverageError: null
        });
      },
      onCancel: () => this.setState({drawing: false, drawingMode: null}),
      onInsufficient: () => this.setState({
        drawing: false,
        drawingMode: null,
        error: _("Hacen falta al menos dos vértices para trazar una polilínea.")
      })
    });
  }

  handleFinishTrace = () => {
    this.editor.finish();
  }

  handleCancelDrawing = () => {
    this.editor.cancel();
  }

  handlePendingNameChange = (e) => {
    this.setState({pendingName: e.target.value});
  }

  handleDiscardPending = () => {
    this._clearCoverageHighlight();
    this.setState({pendingLatLngs: null, pendingName: "", coverageError: null});
  }

  handleSavePending = () => {
    const { pendingLatLngs, pendingName, pendingMode, pendingModel, pendingStep } = this.state;
    if (!pendingLatLngs) return;
    const vertices = bridge.toVertices(pendingLatLngs);

    const body = {name: pendingName, mode: pendingMode, vertices};
    if (pendingMode === 'draped'){
      if (pendingModel) body.model = pendingModel;
      if (pendingStep) body.step = pendingStep;
    }

    this._clearCoverageHighlight();
    this.setState({saving: true, error: "", coverageError: null});
    $.ajax({
      url: this.apiBase(),
      type: 'POST',
      data: JSON.stringify(body),
      contentType: 'application/json'
    }).done(polyline => {
      this.publish(this.singleTask(), polyline, false);
      this.setState(prevState => ({
        polylines: [...prevState.polylines, polyline],
        pendingLatLngs: null,
        pendingName: "",
        saving: false
      }));
    }).fail(req => {
      const data = req.responseJSON || {};
      if (req.status === 422 && data.reason === 'incomplete_coverage'){
        // FR-022, escenario de la US2: se resalta el tramo afectado y se ofrece guardar en
        // modo plano o corregir el trazado; nunca se rellenan cotas.
        this.setState({saving: false, coverageError: data}, () => this._showCoverageHighlight());
      }else{
        this.setState({
          error: data.error || _("No se pudo guardar la polilínea."),
          saving: false
        });
      }
    });
  }

  handleSaveAsFlat = () => {
    this._clearCoverageHighlight();
    this.setState({pendingMode: 'flat', coverageError: null}, this.handleSavePending);
  }

  handleDelete = (polyline) => {
    if (!window.confirm(_("¿Seguro que quieres eliminar esta polilínea?"))) return;
    const layer = this._layers[polyline.id];
    if (layer) PluginsAPI.Map.deleteAnnotation(layer);
  }

  // Un clic en el nombre marca la polilínea (es la que exporta el botón del pie) y de paso la
  // centra en el mapa.
  handleSelect = (polyline) => {
    this.setState({selectedId: polyline.id});
    const layer = this._layers[polyline.id];
    if (layer && layer.getBounds) this.props.map.fitBounds(layer.getBounds());
  }

  selectedPolyline = () => this.state.polylines.find(p => p.id === this.state.selectedId) || null;

  handleExportGeometryChange = (e) => {
    this.setState({exportGeometry: e.target.value});
  }

  handleExport = () => {
    const selected = this.selectedPolyline();
    if (!selected) return;
    // El paso densificado solo existe en las 3D; en una 2D el backend cae a los vértices igual,
    // pero se manda 'vertices' para que la URL diga lo que de verdad se exporta (FR-032, FR-034).
    const geometry = selected.mode === 'draped' ? this.state.exportGeometry : 'vertices';
    bridge.downloadExport(this.taskId(), geometry, selected.id);
  }

  // --- Renombrado, edición de geometría y elevar/aplanar (US4) ------------------------------

  _updatePolylineInState = (updated) => {
    this.setState(prevState => ({
      polylines: prevState.polylines.map(p => p.id === updated.id ? updated : p)
    }));
  }

  handleStartRename = (polyline) => {
    this.setState({editingNameId: polyline.id, editingNameValue: polyline.name});
  }

  handleRenameValueChange = (e) => {
    this.setState({editingNameValue: e.target.value});
  }

  handleCancelRename = () => {
    this.setState({editingNameId: null, editingNameValue: ""});
  }

  handleSaveRename = (polyline) => {
    // Evita el doble envío: Enter dispara el guardado y desmonta el input, lo que a su vez
    // puede disparar onBlur sobre el mismo campo.
    if (this.state.editingNameId !== polyline.id) return;
    const name = this.state.editingNameValue;
    $.ajax({
      url: `${this.apiBase()}/${polyline.id}`,
      type: 'PATCH',
      data: JSON.stringify({name}),
      contentType: 'application/json'
    }).done(updated => {
      this._updatePolylineInState(updated);
      this.setState({editingNameId: null, editingNameValue: ""});
      const layer = this._layers[polyline.id];
      if (layer) bridge.renamePolyline(layer, updated.name); // FR-029: refleja el nombre en el panel de capas del core
    }).fail(req => {
      this.setState({
        error: (req.responseJSON && req.responseJSON.error) || _("No se pudo renombrar la polilínea."),
        editingNameId: null
      });
    });
  }

  handleToggleEditGeometry = (polyline) => {
    const layer = this._layers[polyline.id];
    if (!layer) return;

    if (this.state.editingGeometryId === polyline.id){
      this.editor.stopEditing();
      this.setState({editingGeometryId: null});
      return;
    }

    this.editor.startEditing(layer, {
      onChange: (latlngs) => this.handleGeometryChanged(polyline.id, latlngs),
      // El editor se detiene solo si la polilínea desaparece del mapa (borrada u ocultada
      // desde el panel de capas del core); el panel tiene que soltar el modo edición para que
      // el botón no siga diciendo "Listo" sobre una polilínea que ya no está.
      onStop: () => this.setState(prevState => (
        prevState.editingGeometryId === polyline.id ? {editingGeometryId: null} : null
      ))
    });
    this.setState({editingGeometryId: polyline.id, error: ""});
  }

  handleGeometryChanged = (polylineId, latlngs) => {
    const vertices = bridge.toVertices(latlngs);

    // Cada arrastre o inserción de nodo dispara su propio PATCH, y en una polilínea 3D el
    // servidor vuelve a muestrear el DEM antes de responder. Sin cancelar el anterior, dos
    // respuestas podían llegar en orden inverso y dejar en el panel una geometría más vieja que
    // la del mapa — con la que además se revertiría si el siguiente PATCH fallara.
    const inFlight = this._geometryRequests[polylineId];
    if (inFlight) inFlight.abort();

    const req = $.ajax({
      url: `${this.apiBase()}/${polylineId}`,
      type: 'PATCH',
      data: JSON.stringify({vertices}),
      contentType: 'application/json'
    });
    this._geometryRequests[polylineId] = req;
    // Solo suelta la referencia si sigue siendo la suya: una petición que se resolvió justo
    // antes de que la abortaran no debe descartar a la que ya ocupó su sitio.
    const release = () => {
      if (this._geometryRequests[polylineId] === req) delete this._geometryRequests[polylineId];
    };

    req.done(updated => {
      release();
      this._updatePolylineInState(updated);
    }).fail(xhr => {
      if (xhr.statusText === 'abort') return; // lo cancelamos nosotros: ya hay otro PATCH en curso
      release();
      const data = xhr.responseJSON || {};
      // FR-019: la edición se rechaza entera y la polilínea conserva su geometría anterior;
      // el layer en el mapa ya refleja el intento fallido, así que se revierte visualmente.
      const polyline = this.state.polylines.find(p => p.id === polylineId);
      const layer = this._layers[polylineId];
      if (polyline && layer) layer.setLatLngs(bridge.toLatLngs(polyline.vertices));
      this.setState({
        error: data.error || _("No se pudo actualizar la geometría."),
      });
      this.editor.stopEditing();
      this.setState({editingGeometryId: null});
    });
  }

  // --- Resalte de tramos sin cobertura (T037) -----------------------------------------------

  _cumulativeLengths(latlngs){
    const out = [0];
    for (let i = 1; i < latlngs.length; i++) out.push(out[i - 1] + latlngs[i - 1].distanceTo(latlngs[i]));
    return out;
  }

  _segmentBetween(latlngs, fractionStart, fractionEnd){
    const cum = this._cumulativeLengths(latlngs);
    const total = cum[cum.length - 1] || 1;
    const targetStart = fractionStart * total;
    const targetEnd = fractionEnd * total;
    const points = latlngs.filter((_ll, i) => cum[i] >= targetStart - 1e-6 && cum[i] <= targetEnd + 1e-6);
    return points.length >= 2 ? points : latlngs;
  }

  _showCoverageHighlight(){
    this._clearCoverageHighlight();
    const { pendingLatLngs, coverageError } = this.state;
    if (!pendingLatLngs || !coverageError) return;
    this._coverageHighlightLayers = coverageError.missing_ranges.map(([a, b]) => {
      const segment = this._segmentBetween(pendingLatLngs, a, b);
      return L.polyline(segment, {color: '#e53935', weight: 6, opacity: 0.85}).addTo(this.props.map);
    });
  }

  _clearCoverageHighlight(){
    this._coverageHighlightLayers.forEach(l => this.props.map.removeLayer(l));
    this._coverageHighlightLayers = [];
  }

  renderMultiTaskNotice(){
    return (<div className="annotations-notice">
      {_("La herramienta de trazado necesita que el mapa muestre una sola tarea. Las polilíneas ya guardadas se siguen mostrando en el panel de capas.")}
    </div>);
  }

  renderCoverageError(){
    return (<div className="annotations-coverage-error">
      <p>{_("Parte del recorrido no tiene datos de elevación.")}</p>
      <div className="annotations-coverage-actions">
        <button className="btn btn-xs btn-default" onClick={this.handleSaveAsFlat}>{_("Guardar como 2D")}</button>
        <button className="btn btn-xs btn-default" onClick={() => { this._clearCoverageHighlight(); this.setState({coverageError: null}); }}>{_("Ajustar trazado")}</button>
      </div>
    </div>);
  }

  renderPendingForm(){
    const { pendingName, saving, pendingMode, pendingModel, pendingStep, elevationCaps, coverageError } = this.state;
    const hasDem = this.hasDem();
    const bothModels = hasDem && elevationCaps.available.length > 1;
    const draped = pendingMode === 'draped';

    return (<div className="annotations-pending">
      <div className="annotations-pending-type">
        {_("Nueva polilínea")} <span className={"annotations-badge " + (draped ? "annotations-badge-3d" : "annotations-badge-2d")}>
          {draped ? _("3D") : _("2D")}
        </span>
      </div>

      <label>{_("Nombre")}</label>
      <input type="text" value={pendingName} placeholder={_("Polilínea sin nombre")}
             onChange={this.handlePendingNameChange} disabled={saving} />

      {draped ? (<div className="annotations-elevation-options">
        {bothModels ? (<div>
          <label>{_("Modelo")}</label>
          <select value={pendingModel} disabled={saving}
                  onChange={e => this.setState({pendingModel: e.target.value})}>
            <option value="dsm">{_("Superficie (DSM)")}</option>
            <option value="dtm">{_("Terreno (DTM)")}</option>
          </select>
        </div>) : null}
        <label>{_("Paso de densificación (m)")}</label>
        <input type="number" step="0.01" disabled={saving}
               min={elevationCaps.step_range[0]} max={elevationCaps.step_range[1]}
               value={pendingStep === null ? '' : pendingStep}
               onChange={e => this.setState({pendingStep: parseFloat(e.target.value)})} />
      </div>) : null}

      {coverageError ? this.renderCoverageError() : null}

      <div className="annotations-pending-actions">
        <button className="btn btn-sm btn-primary" onClick={this.handleSavePending} disabled={saving}>{_("Guardar")}</button>
        <button className="btn btn-sm btn-default" onClick={this.handleDiscardPending} disabled={saving}>{_("Descartar")}</button>
      </div>
    </div>);
  }

  renderDrawingProgress(){
    const { progressLength, progressVertices } = this.state;
    const lenStr = unitSystem().length(progressLength).toString();
    return (<div className="annotations-progress">
      {_("Trazando")}: {progressVertices} {_("vértices")}, {lenStr}.
      {" "}<a href="javascript:void(0)" onClick={this.handleCancelDrawing}>{_("Cancelar (Esc)")}</a>
    </div>);
  }

  renderTypeBadge(mode){
    const draped = mode === 'draped';
    return (<span className={"annotations-badge " + (draped ? "annotations-badge-3d" : "annotations-badge-2d")}
                  title={draped ? _("Sobre el terreno, con cotas del modelo de elevación") : _("Plana, sin cotas")}>
      {draped ? _("3D") : _("2D")}
    </span>);
  }

  renderList(){
    const { polylines, editingNameId, editingNameValue, editingGeometryId, selectedId } = this.state;
    if (polylines.length === 0) return (<div className="annotations-empty">{_("Todavía no hay polilíneas en esta tarea.")}</div>);

    return (<div className="annotations-list-wrapper">
    <ul className="annotations-list">
      {polylines.map(p => {
        const isEditingName = editingNameId === p.id;
        const isEditingGeometry = editingGeometryId === p.id;
        const isSelected = selectedId === p.id;

        return (<li key={p.id} className={"annotations-list-item" + (isSelected ? " annotations-list-item-selected" : "")}>
          <div className="annotations-list-row">
            {this.renderTypeBadge(p.mode)}
            {isEditingName ? (
              <input type="text" className="annotations-rename-input" value={editingNameValue} autoFocus
                     onChange={this.handleRenameValueChange}
                     onKeyDown={e => {
                       if (e.key === 'Enter') this.handleSaveRename(p);
                       if (e.key === 'Escape') this.handleCancelRename();
                     }}
                     onBlur={() => this.handleSaveRename(p)} />
            ) : (
              <a href="javascript:void(0)" className="annotations-list-name"
                 title={_("Seleccionar y centrar en el mapa")} onClick={() => this.handleSelect(p)}>{p.name}</a>
            )}
            <span className="annotations-list-actions">
              {!isEditingName ? (
                <a href="javascript:void(0)" title={_("Rename")} onClick={() => this.handleStartRename(p)}>
                  <i className="fa fa-pencil-alt"></i>
                </a>
              ) : null}
              <a href="javascript:void(0)" className="annotations-list-delete" title={_("Delete")} onClick={() => this.handleDelete(p)}>
                <i className="fa fa-trash"></i>
              </a>
            </span>
          </div>

          {p.elevation ? (
            <div className="annotations-list-metrics">
              <div>{_("Terreno")}: {unitSystem().length(p.elevation.surface_length).toString()}
                {" "}({_("paso")} {unitSystem().length(p.elevation.step).toString()})</div>
              <div>{_("Planta")}: {unitSystem().length(p.plan_length).toString()}</div>
              <div>{_("Desnivel")}: {unitSystem().length(p.elevation.elevation_gain).toString()}</div>
              {p.elevation.stale ? (<div className="annotations-stale">{_("Muestreo obsoleto: el modelo de elevación cambió desde entonces.")}</div>) : null}
            </div>
          ) : (<div className="annotations-list-metrics">
            <span className="annotations-list-length">{unitSystem().length(p.plan_length).toString()}</span>
          </div>)}

          <div className="annotations-list-toolbar">
            <button className={"btn btn-xs " + (isEditingGeometry ? "btn-warning" : "btn-default")}
                    onClick={() => this.handleToggleEditGeometry(p)}>
              {isEditingGeometry ? _("Listo") : _("Editar geometría")}
            </button>
          </div>
          {isEditingGeometry ? (<div className="annotations-edit-hint">
            {_("Arrastra un nodo para moverlo, click sobre la línea para añadir uno y click derecho sobre un nodo para quitarlo.")}
          </div>) : null}
        </li>);
      })}
    </ul>
    </div>);
  }

  renderExportControls(){
    const { exportGeometry } = this.state;
    const selected = this.selectedPolyline();
    const draped = !!selected && selected.mode === 'draped';

    return (<div className="annotations-export">
      {/* El paso densificado solo existe en las 3D: en una 2D los vértices son toda la línea. */}
      {draped ? (<select value={exportGeometry} onChange={this.handleExportGeometryChange}>
        <option value="vertices">{_("Vértices")}</option>
        <option value="densified">{_("Densificada")}</option>
      </select>) : null}
      <button className="btn btn-sm btn-default" onClick={this.handleExport} disabled={!selected}
              title={selected ? "" : _("Selecciona una polilínea de la lista.")}>
        <i className="fa fa-download"></i> {selected ? _("Exportar seleccionada") : _("Exportar GeoJSON")}
      </button>
    </div>);
  }

  render(){
    const { onClose } = this.props;
    const { drawing, drawingMode, pendingLatLngs, polylines } = this.state;
    const single = this.singleTask();

    return (<div className="annotations-panel">
      <div className="title">{_("Annotations")} <a href="javascript:void(0)" className="close-button" onClick={onClose}><i className="fa fa-times"></i></a></div>
      <ErrorMessage bind={[this, 'error']} />

      {single ? (<div className="annotations-toolbar">
          {drawing ? (
            <button className="btn btn-sm btn-danger" onClick={this.handleFinishTrace}>
              {_("Finalizar trazado")} {this.renderTypeBadge(drawingMode)}
            </button>
          ) : (<React.Fragment>
            <button className="btn btn-sm btn-primary" onClick={() => this.handleTrace('flat')}>
              {_("Polilínea 2D")}
            </button>
            <button className="btn btn-sm btn-primary" onClick={() => this.handleTrace('draped')}
                    disabled={!this.hasDem()}
                    title={this.hasDem() ? _("Sigue el relieve usando el modelo de elevación") : _("Esta tarea no tiene modelo de elevación.")}>
              {_("Polilínea 3D")}
            </button>
          </React.Fragment>)}
        </div>) : this.renderMultiTaskNotice()}

      {drawing ? this.renderDrawingProgress() : null}
      {pendingLatLngs ? this.renderPendingForm() : null}

      {single ? this.renderList() : null}
      {single && polylines.length > 0 ? this.renderExportControls() : null}
    </div>);
  }
}
