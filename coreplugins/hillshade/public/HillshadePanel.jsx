import React from 'react';
import PropTypes from 'prop-types';
import Storage from 'webodm/classes/Storage';
import L from 'leaflet';
import './HillshadePanel.scss';
import ErrorMessage from 'webodm/components/ErrorMessage';
import Workers from 'webodm/classes/Workers';
import { _ } from 'webodm/classes/gettext';

export default class HillshadePanel extends React.Component {
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
        processing: false,
        azimuth: Storage.getItem("last_hillshade_azimuth") || "315",
        altitude: Storage.getItem("last_hillshade_altitude") || "30",
        opacity: Storage.getItem("last_hillshade_opacity") || "0.7",
        hillshadeLayer: null
    };
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
                this.setState({permanentError: _("No DSM or DTM is available. To compute a hillshade, make sure to process a task with either the --dsm or --dtm option checked.")});
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
  }

  handleSelectLayer = e => {
    this.setState({layer: e.target.value});
  }

  handleChangeAzimuth = e => {
    this.setState({azimuth: e.target.value});
  }

  handleChangeAltitude = e => {
    this.setState({altitude: e.target.value});
  }

  handleChangeOpacity = e => {
    const opacity = parseFloat(e.target.value);
    this.setState({opacity: e.target.value});
    Storage.setItem("last_hillshade_opacity", e.target.value);
    if (this.state.hillshadeLayer){
      this.state.hillshadeLayer.setOpacity(opacity);
    }
  }

  handleClear = () => {
    const { map } = this.props;

    if (this.state.hillshadeLayer){
      map.removeLayer(this.state.hillshadeLayer);
    }
    this.setState({hillshadeLayer: null});
  }

  handleCompute = () => {
    const { azimuth, altitude, layer, task } = this.state;

    this.setState({processing: true, error: ""});
    Storage.setItem("last_hillshade_azimuth", azimuth);
    Storage.setItem("last_hillshade_altitude", altitude);

    const taskId = task.id;

    this.generateReq = $.ajax({
        type: 'POST',
        url: `/api/plugins/hillshade/task/${taskId}/hillshade/generate`,
        data: { azimuth: parseFloat(azimuth), altitude: parseFloat(altitude), layer }
    }).done(result => {
        if (result.celery_task_id){
          Workers.waitForCompletion(result.celery_task_id, error => {
            if (error){
              this.setState({processing: false, error});
            }else{
              const getUrl = `/api/plugins/hillshade/task/${taskId}/hillshade/result/`;
              Workers.getOutput(result.celery_task_id, (err, output) => {
                if (err){
                  this.setState({processing: false, error: JSON.stringify(err)});
                }else{
                  const bounds = output.bounds;
                  const imageUrl = `/api/plugins/hillshade/task/${taskId}/hillshade/result/${result.celery_task_id}?serve=image`;

                  // Remove previous overlay
                  if (this.state.hillshadeLayer){
                    this.props.map.removeLayer(this.state.hillshadeLayer);
                  }

                  const overlay = L.imageOverlay(imageUrl, bounds, {opacity: parseFloat(this.state.opacity)}).addTo(this.props.map);
                  this.setState({processing: false, hillshadeLayer: overlay});
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

  render(){
    const { loading, layers, error, permanentError, layer,
            processing, azimuth, altitude, opacity,
            hillshadeLayer } = this.state;

    const canCompute = !processing && layer !== "";

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
          <label className="col-sm-3 control-label">{_("Azimuth:")}</label>
          <div className="col-sm-7">
            <input type="range" className="azimuth-range" min="0" max="360" step="1" value={azimuth} onChange={this.handleChangeAzimuth} />
          </div>
          <div className="col-sm-2 slider-value">
            {azimuth}&deg;
          </div>
        </div>

        <div className="row form-group form-inline">
          <label className="col-sm-3 control-label">{_("Altitude:")}</label>
          <div className="col-sm-7">
            <input type="range" className="altitude-range" min="0" max="90" step="1" value={altitude} onChange={this.handleChangeAltitude} />
          </div>
          <div className="col-sm-2 slider-value">
            {altitude}&deg;
          </div>
        </div>

        <div className="row form-group form-inline opacity-row">
          <label className="col-sm-3 control-label">{_("Opacity:")}</label>
          <div className="col-sm-7">
            <input type="range" className="opacity-range" min="0" max="1" step="0.05" value={opacity} onChange={this.handleChangeOpacity} />
          </div>
          <div className="col-sm-2 slider-value">
            {Math.round(opacity * 100)}%
          </div>
        </div>

        <div className="row action-buttons">
          <div className="col-sm-3">
            {hillshadeLayer ? <a title={_("Clear")} href="javascript:void(0);" onClick={this.handleClear}>
              <i className="fa fa-trash"></i>
            </a> : ""}
          </div>
          <div className="col-sm-9 text-right">
            <button onClick={this.handleCompute}
                    disabled={!canCompute} type="button" className="btn btn-sm btn-primary">
              {processing ? <i className="fa fa-spin fa-circle-notch"/> : <i className="fa fa-mountain"/>} {_("Compute Hillshade")}
            </button>
          </div>
        </div>
      </div>);
    }

    return (<div className="hillshade-panel">
      <span className="close-button" onClick={this.props.onClose}/>
      <div className="title">{_("Hillshade Analysis")}</div>
      <hr/>
      {content}
    </div>);
  }
}
