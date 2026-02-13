import React from 'react';
import PropTypes from 'prop-types';
import Storage from 'webodm/classes/Storage';
import L from 'leaflet';
import './WatershedPanel.scss';
import ErrorMessage from 'webodm/components/ErrorMessage';
import Workers from 'webodm/classes/Workers';
import { _ } from 'webodm/classes/gettext';

export default class WatershedPanel extends React.Component {
  static propTypes = {
    onClose: PropTypes.func.isRequired,
    tasks: PropTypes.array.isRequired,
    isShowed: PropTypes.bool.isRequired,
    map: PropTypes.object.isRequired
  }

  constructor(props){
    super(props);

    this.state = {
        error: "",
        permanentError: "",
        layer: "",
        layers: [],
        loading: true,
        task: props.tasks[0] || null,
        picking: false,
        processing: false,
        lat: null,
        lng: null,
        snapDistance: Storage.getItem("last_watershed_snap_distance") || "100",
        opacity: Storage.getItem("last_watershed_opacity") || "0.7",
        watershedLayer: null,
        markerLayer: null,
        watershedArea: null
    };
  }

  componentDidMount(){
    PluginsAPI.Map.onHandleClick(this.clickHandler);
  }

  componentDidUpdate(){
    if (this.props.isShowed && this.state.loading){
      const {id, project} = this.state.task;

      this.loadingReq = $.getJSON(`/api/projects/${project}/tasks/${id}/`)
          .done(res => {
              const { available_assets } = res;
              let layers = [];

              if (available_assets.indexOf("dsm.tif") !== -1) layers.push("DSM");
              if (available_assets.indexOf("dtm.tif") !== -1) layers.push("DTM");

              if (layers.length > 0){
                this.setState({layers, layer: layers[0]});
              }else{
                this.setState({permanentError: _("No DSM or DTM is available. To compute a watershed, make sure to process a task with either the --dsm or --dtm option checked.")});
              }
          })
          .fail(() => {
            this.setState({permanentError: _("Cannot retrieve information for task. Are you connected to the internet?")})
          })
          .always(() => {
            this.setState({loading: false});
            this.loadingReq = null;
          });
    }
  }

  componentWillUnmount(){
    if (this.loadingReq){
      this.loadingReq.abort();
      this.loadingReq = null;
    }
    if (this.generateReq){
      this.generateReq.abort();
      this.generateReq = null;
    }
    this.handleClear();
    PluginsAPI.Map.offHandleClick(this.clickHandler);
  }

  clickHandler = (e) => {
    if (this.state.picking){
      const { lat, lng } = e.latlng;
      const { map } = this.props;

      if (this.state.markerLayer){
        map.removeLayer(this.state.markerLayer);
      }

      const marker = L.circleMarker([lat, lng], {
        radius: 8,
        color: '#fff',
        weight: 2,
        fillColor: '#0096ff',
        fillOpacity: 0.9
      }).addTo(map);
      this.setState({lat, lng, picking: false, markerLayer: marker});
      return true;
    }
    return false;
  }

  handleSelectLayer = e => {
    this.setState({layer: e.target.value});
  }

  handleChangeSnapDistance = e => {
    this.setState({snapDistance: e.target.value});
  }

  handleChangeOpacity = e => {
    const opacity = parseFloat(e.target.value);
    this.setState({opacity: e.target.value});
    Storage.setItem("last_watershed_opacity", e.target.value);
    if (this.state.watershedLayer){
      this.state.watershedLayer.setOpacity(opacity);
    }
  }

  handlePickPoint = () => {
    this.setState({picking: !this.state.picking});
  }

  handleClear = () => {
    const { map } = this.props;

    if (this.state.watershedLayer){
      map.removeLayer(this.state.watershedLayer);
    }
    if (this.state.markerLayer){
      map.removeLayer(this.state.markerLayer);
    }
    this.setState({watershedLayer: null, markerLayer: null, lat: null, lng: null, watershedArea: null});
  }

  handleCompute = () => {
    const { lat, lng, snapDistance, layer, task } = this.state;

    this.setState({processing: true, error: "", watershedArea: null});
    Storage.setItem("last_watershed_snap_distance", snapDistance);

    const taskId = task.id;

    this.generateReq = $.ajax({
        type: 'POST',
        url: `/api/plugins/watershed/task/${taskId}/watershed/generate`,
        data: { lat, lng, snap_distance: parseFloat(snapDistance), layer }
    }).done(result => {
        if (result.celery_task_id){
          Workers.waitForCompletion(result.celery_task_id, error => {
            if (error){
              this.setState({processing: false, error});
            }else{
              const getUrl = `/api/plugins/watershed/task/${taskId}/watershed/result/`;
              Workers.getOutput(result.celery_task_id, (err, output) => {
                if (err){
                  this.setState({processing: false, error: JSON.stringify(err)});
                }else{
                  const bounds = output.bounds;
                  const area = output.area;
                  const imageUrl = `/api/plugins/watershed/task/${taskId}/watershed/result/${result.celery_task_id}?serve=image`;

                  if (this.state.watershedLayer){
                    this.props.map.removeLayer(this.state.watershedLayer);
                  }

                  const overlay = L.imageOverlay(imageUrl, bounds, {opacity: parseFloat(this.state.opacity)}).addTo(this.props.map);
                  this.setState({processing: false, watershedLayer: overlay, watershedArea: area});
                }
              }, getUrl);
            }
          });
        }else if (result.error){
            this.setState({processing: false, error: result.error});
        }else{
            this.setState({processing: false, error: "Invalid response: " + JSON.stringify(result)});
        }
    }).fail(error => {
        this.setState({processing: false, error: JSON.stringify(error)});
    });
  }

  formatArea = (area) => {
    if (area >= 1000000) return (area / 1000000).toFixed(2) + " km\u00B2";
    if (area >= 10000) return (area / 10000).toFixed(2) + " ha";
    return area.toFixed(1) + " m\u00B2";
  }

  render(){
    const { loading, layers, error, permanentError, layer,
            picking, processing, lat, lng, snapDistance, opacity,
            watershedLayer, markerLayer, watershedArea } = this.state;

    const canCompute = lat !== null && lng !== null && !processing;

    let content = "";
    if (loading) content = (<span><i className="fa fa-circle-notch fa-spin"></i> {_("Loading...")}</span>);
    else if (permanentError) content = (<div className="alert alert-warning">{permanentError}</div>);
    else{
      content = (<div>
        <ErrorMessage bind={[this, "error"]} />
        <div className="row form-group form-inline">
          <label className="col-sm-3 control-label">{_("Layer:")}</label>
          <div className="col-sm-9">
            <select className="form-control" value={layer} onChange={this.handleSelectLayer}>
              {layers.map(l => <option key={l} value={l}>{l}</option>)}
            </select>
          </div>
        </div>

        <div className="row form-group form-inline">
          <label className="col-sm-3 control-label">{_("Snap:")}</label>
          <div className="col-sm-9">
            <input type="number" className="form-control snap-input" value={snapDistance} onChange={this.handleChangeSnapDistance} min="0" step="0.001" />
          </div>
        </div>

        <div className="row form-group">
          <div className="col-sm-12">
            <button onClick={this.handlePickPoint}
                    type="button" className={"btn btn-sm btn-default btn-pick" + (picking ? " active" : "")}>
              <i className="fa fa-crosshairs"></i> {picking ? _("Click on map...") : _("Pick Pour Point on Map")}
            </button>
          </div>
        </div>

        {lat !== null && lng !== null ?
          <div className="row form-group">
            <div className="col-sm-12 coords-display">
              <i className="fa fa-map-marker"></i> {lat.toFixed(6)}, {lng.toFixed(6)}
            </div>
          </div>
        : ""}

        <div className="row form-group form-inline opacity-row">
          <label className="col-sm-3 control-label">{_("Opacity:")}</label>
          <div className="col-sm-7">
            <input type="range" className="opacity-range" min="0" max="1" step="0.05" value={opacity} onChange={this.handleChangeOpacity} />
          </div>
          <div className="col-sm-2 opacity-value">
            {Math.round(opacity * 100)}%
          </div>
        </div>

        {watershedArea !== null ?
          <div className="row form-group">
            <div className="col-sm-12 area-display">
              <i className="fa fa-ruler-combined"></i> {_("Area:")} {this.formatArea(watershedArea)}
            </div>
          </div>
        : ""}

        <div className="row action-buttons">
          <div className="col-sm-3">
            {watershedLayer || markerLayer ? <a title={_("Clear")} href="javascript:void(0);" onClick={this.handleClear}>
              <i className="fa fa-trash"></i>
            </a> : ""}
          </div>
          <div className="col-sm-9 text-right">
            <button onClick={this.handleCompute}
                    disabled={!canCompute} type="button" className="btn btn-sm btn-primary">
              {processing ? <i className="fa fa-spin fa-circle-notch"/> : <i className="fa fa-water"/>} {_("Compute Watershed")}
            </button>
          </div>
        </div>
      </div>);
    }

    return (<div className="watershed-panel">
      <span className="close-button" onClick={this.props.onClose}/>
      <div className="title">{_("Watershed Analysis")}</div>
      <hr/>
      {content}
    </div>);
  }
}
