import L from 'leaflet';
import ReactDOM from 'ReactDOM';
import React from 'React';
import PropTypes from 'prop-types';
import { _ } from 'webodm/classes/gettext';
import './Training.scss';
import TrainingPanel from './TrainingPanel';
import { bringToFront, sendToBack } from './panelStacking';

class TrainingButton extends React.Component {
  static propTypes = {
    tasks: PropTypes.array.isRequired,
    map: PropTypes.object.isRequired,
    container: PropTypes.object // contenedor del control, para el apilado entre plugins
  }

  constructor(props){
    super(props);
    this.state = { showPanel: false };
  }

  handleOpen = () => {
    this.setState({showPanel: true});
    // Al abrir, este control pasa por delante de los paneles de otros plugins: todos comparten la
    // esquina topright y el mismo nivel base, así que a igualdad de z-index decide el orden del
    // DOM y el botón de uno puede acabar dibujado dentro del panel abierto de otro.
    bringToFront(this.props.container);
  }

  handleClose = () => {
    this.setState({showPanel: false});
    sendToBack(this.props.container);
  }

  render(){
    const { showPanel } = this.state;

    return (<div className={showPanel ? "open" : ""}>
        <a href="javascript:void(0);"
            onClick={this.handleOpen}
            title={_("Training")}
            className="leaflet-control-training-button leaflet-bar-part theme-secondary"></a>
        <TrainingPanel onClose={this.handleClose}
                       tasks={this.props.tasks}
                       map={this.props.map}
                       isShowed={showPanel} />
      </div>);
  }
}

export default L.Control.extend({
  options: {
    position: 'topright'
  },

  onAdd: function (map) {
    var container = L.DomUtil.create('div', 'leaflet-control-training leaflet-bar leaflet-control');
    L.DomEvent.disableClickPropagation(container);
    L.DomEvent.disableScrollPropagation(container);

    ReactDOM.render(<TrainingButton map={map}
                                    tasks={this.options.tasks}
                                    container={container} />, container);

    return container;
  }
});
