import L from 'leaflet';
import ReactDOM from 'ReactDOM';
import React from 'React';
import PropTypes from 'prop-types';
import './Viewshed.scss';
import ViewshedPanel from './ViewshedPanel';

class ViewshedButton extends React.Component {
  static propTypes = {
    tasks: PropTypes.array.isRequired,
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
            className="leaflet-control-viewshed-button leaflet-bar-part theme-secondary"></a>
        <ViewshedPanel map={this.props.map} isShowed={showPanel} tasks={this.props.tasks} onClose={this.handleClose} />
    </div>);
  }
}

export default L.Control.extend({
    options: {
        position: 'topright'
    },

    onAdd: function (map) {
        var container = L.DomUtil.create('div', 'leaflet-control-viewshed leaflet-bar leaflet-control');
        L.DomEvent.disableClickPropagation(container);
        ReactDOM.render(<ViewshedButton map={this.options.map} tasks={this.options.tasks} />, container);

        return container;
    }
});
