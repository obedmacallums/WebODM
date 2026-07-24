import L from 'leaflet';
import ReactDOM from 'ReactDOM';
import React from 'React';
import PropTypes from 'prop-types';
import { _ } from 'webodm/classes/gettext';
import './Realign.scss';
import RealignPanel from './RealignPanel';

class RealignButton extends React.Component {
  static propTypes = {
    tasks: PropTypes.array.isRequired,
    tiles: PropTypes.array.isRequired,
    map: PropTypes.object.isRequired
  }

  constructor(props){
    super(props);

    this.state = {
        showPanel: false
    };
  }

  handleOpen = () => {
    this.setState({showPanel: true});
  }

  handleClose = () => {
    this.setState({showPanel: false});
  }

  render(){
    const { showPanel } = this.state;

    return (<div className={showPanel ? "open" : ""}>
        <a href="javascript:void(0);"
            onClick={this.handleOpen}
            title={_("Realign")}
            className="leaflet-control-realign-button leaflet-bar-part theme-secondary"></a>
        <RealignPanel map={this.props.map}
                      tiles={this.props.tiles}
                      isShowed={showPanel}
                      tasks={this.props.tasks}
                      onClose={this.handleClose} />
    </div>);
  }
}

export default L.Control.extend({
    options: {
        position: 'topright'
    },

    onAdd: function (map) {
        var container = L.DomUtil.create('div', 'leaflet-control-realign leaflet-bar leaflet-control');
        L.DomEvent.disableClickPropagation(container);
        L.DomEvent.disableScrollPropagation(container);
        ReactDOM.render(<RealignButton map={this.options.map} tasks={this.options.tasks} tiles={this.options.tiles} />, container);

        return container;
    }
});
