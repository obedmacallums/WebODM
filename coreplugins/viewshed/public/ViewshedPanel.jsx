import React from 'react';
import PropTypes from 'prop-types';
import L from 'leaflet';
import './ViewshedPanel.scss';
import ErrorMessage from 'webodm/components/ErrorMessage';
import Workers from 'webodm/classes/Workers';
import Utils from 'webodm/classes/Utils';
import { _ } from 'webodm/classes/gettext';

export default class ViewshedPanel extends React.Component {
  static propTypes = {
    onClose: PropTypes.func.isRequired,
    tasks: PropTypes.object.isRequired,
    isShowed: PropTypes.bool.isRequired,
    map: PropTypes.object.isRequired
  }

  constructor(props){
    super(props);

    this.state = {
        checkingAvailability: true,
        permanentError: "",
        error: "",
        capturing: false,
        generating: false,
        observerHeight: "1.6",
        resultLayer: null,
        resultParams: null,
        currentCeleryTaskId: null,
        task: props.tasks[0] || null
    };
  }

  componentDidUpdate(){
    if (this.props.isShowed && this.state.checkingAvailability && !this.loadingReq){
      const { id, project } = this.state.task;

      this.loadingReq = $.getJSON(`/api/projects/${project}/tasks/${id}/`)
        .done(res => {
            const { available_assets } = res;
            const hasDem = available_assets.indexOf("dsm.tif") !== -1 || available_assets.indexOf("dtm.tif") !== -1;

            if (!hasDem){
                this.setState({permanentError: _("Esta tarea no tiene un modelo de elevación (DSM/DTM). Procesa la tarea con la opción --dsm o --dtm para poder usar la herramienta de visibilidad.")});
            }
        })
        .fail(() => {
            this.setState({permanentError: _("No se pudo obtener información de la tarea. ¿Estás conectado a internet?")});
        })
        .always(() => {
            this.setState({checkingAvailability: false});
            this.loadingReq = null;
        });
    }
  }

  componentWillUnmount(){
    if (this.state.capturing) this.stopCapture();

    if (this.loadingReq){
      this.loadingReq.abort();
      this.loadingReq = null;
    }
    if (this.generateReq){
      this.generateReq.abort();
      this.generateReq = null;
    }
    if (this.state.currentCeleryTaskId){
      Workers.cancel(this.state.currentCeleryTaskId);
    }
  }

  isHeightValid = () => {
    const { observerHeight } = this.state;
    if (!Utils.isNumeric(observerHeight)) return false;
    const h = parseFloat(observerHeight);
    return h >= 0 && h <= 500;
  }

  handleHeightChange = e => {
    this.setState({observerHeight: e.target.value});
  }

  handleMapClick = e => {
    const { lat, lng } = e.latlng;
    this.stopCapture();
    this.generateViewshed(lat, lng);
  }

  handleToggleCapture = () => {
    if (this.state.capturing){
      this.stopCapture();
    }else{
      this.setState({capturing: true, error: ""});
      this.props.map.on('click', this.handleMapClick);
      this.props.map.getContainer().style.cursor = 'crosshair';
    }
  }

  stopCapture = () => {
    this.props.map.off('click', this.handleMapClick);
    this.props.map.getContainer().style.cursor = '';
    this.setState({capturing: false});
  }

  generateViewshed = (lat, lng) => {
    if (!this.isHeightValid()){
      this.setState({error: _("La altura del observador debe ser un número entre 0 y 500 metros.")});
      return;
    }

    // Un análisis a la vez: cancela/descarta cualquier análisis previo en curso (FR-008, edge case de mezcla de resultados)
    if (this.state.currentCeleryTaskId) Workers.cancel(this.state.currentCeleryTaskId);
    if (this.generateReq) this.generateReq.abort();

    this.setState({generating: true, error: "", currentCeleryTaskId: null});

    const taskId = this.state.task.id;
    const data = {
      lat, lng,
      observer_height: parseFloat(this.state.observerHeight)
    };

    this.generateReq = $.ajax({
        type: 'POST',
        url: `/api/plugins/viewshed/task/${taskId}/viewshed/generate`,
        data
    }).done(result => {
        if (result.celery_task_id){
          this.setState({currentCeleryTaskId: result.celery_task_id});

          Workers.waitForCompletion(result.celery_task_id, error => {
            if (error){
              this.setState({generating: false, error, currentCeleryTaskId: null});
            }else{
              const fileUrl = `/api/plugins/viewshed/task/${taskId}/viewshed/download/${result.celery_task_id}`;
              this.addResultLayer(fileUrl, lat, lng);
            }
          });
        }else if (result.error){
            this.setState({generating: false, error: result.error});
        }else{
            this.setState({generating: false, error: _("Respuesta inválida del servidor: ") + JSON.stringify(result)});
        }
    }).fail(error => {
        this.setState({generating: false, error: JSON.stringify(error)});
    });
  }

  addResultLayer = (url, lat, lng) => {
    const { map } = this.props;

    $.getJSON(url)
     .done(geojson => {
      try{
        // Un nuevo análisis reemplaza al anterior (FR-008)
        this.removeResultLayer();

        const layer = L.geoJSON(geojson, {
          style: () => ({color: "#00e676", weight: 1, fillColor: "#00e676", fillOpacity: 0.35})
        });
        layer.addTo(map);

        this.setState({
          generating: false,
          currentCeleryTaskId: null,
          resultLayer: layer,
          resultParams: {lat, lng, observerHeight: this.state.observerHeight}
        });
      }catch(e){
        this.setState({generating: false, error: e.message});
      }
     })
     .fail(() => {
        this.setState({generating: false, error: _("No se pudo descargar el resultado del análisis.")});
     });
  }

  removeResultLayer = () => {
    const { map } = this.props;

    if (this.state.resultLayer){
      map.removeLayer(this.state.resultLayer);
      this.setState({resultLayer: null, resultParams: null});
    }
  }

  render(){
    const { checkingAvailability, permanentError, capturing, generating, observerHeight, resultLayer } = this.state;

    let content = "";
    if (checkingAvailability) content = (<span><i className="fa fa-circle-notch fa-spin"></i> {_("Cargando…")}</span>);
    else if (permanentError) content = (<div className="alert alert-warning">{permanentError}</div>);
    else{
      const heightValid = this.isHeightValid();

      content = (<div>
        <ErrorMessage bind={[this, "error"]} />

        <div className="row form-group form-inline">
          <label className="col-sm-7 control-label">{_("Altura del observador (m):")}</label>
          <div className="col-sm-5">
            <input type="number"
                   className={"form-control " + (!heightValid ? "theme-background-failed" : "")}
                   value={observerHeight}
                   disabled={generating}
                   onChange={this.handleHeightChange} />
          </div>
        </div>

        <div className="row action-buttons">
          <div className="col-sm-12 text-right">
            {resultLayer ? <button type="button" className="btn btn-sm btn-secondary" disabled={generating} onClick={this.removeResultLayer}>
                <i className="fa fa-trash"/> {_("Quitar")}
              </button> : ""}
            {" "}
            <button type="button" className="btn btn-sm btn-primary" disabled={!heightValid || generating} onClick={this.handleToggleCapture}>
              {generating ? <i className="fa fa-spin fa-circle-notch"/> : <i className="glyphicon glyphicon-map-marker"/>}
              {" "}
              {generating ? _("Calculando…") : (capturing ? _("Haz clic en el mapa…") : _("Seleccionar punto"))}
            </button>
          </div>
        </div>
      </div>);
    }

    return (<div className="viewshed-panel">
      <span className="close-button" onClick={this.props.onClose}/>
      <div className="title">{_("Viewshed")}</div>
      <hr/>
      {content}
    </div>);
  }
}
